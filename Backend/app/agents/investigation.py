import concurrent.futures
import json
import time
import uuid
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from sqlalchemy.orm import Session

from app.agents.llm_client import get_llm
from app.models.audit_log import AuditLog
from app.models.enums import ActorType, InvestigationStatus
from app.models.incident import Incident
from app.models.investigation import Investigation
from app.prompts.investigation_prompt import INVESTIGATION_SYSTEM_PROMPT
from app.services.audit_log_service import log_event
from app.tools.registry import build_investigation_tools

MAX_TOOL_CALLS = 8
RECURSION_LIMIT = 30
MAX_WALL_SECONDS = 60
CONFIDENCE_THRESHOLD = 0.5


class InvestigationState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_call_count: int
    tool_trace: list


def _incident_summary(incident: Incident) -> str:
    lines = [
        f"Incident Type: {incident.type.value}", f"Severity: {incident.severity.value}",
        f"Description: {incident.description or '(none provided)'}", "",
        "Known linked entity ids (use these directly with your tools -- do not guess ids):",
        f"- shipment_id: {incident.shipment_id or 'unknown'}", f"- supplier_id: {incident.supplier_id or 'unknown'}",
        f"- product_id: {incident.product_id or 'unknown'}", f"- warehouse_id: {incident.warehouse_id or 'unknown'}",
        "", "Investigate this incident now.",
    ]
    return "\n".join(lines)


def parse_final_answer(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"root_cause": None, "evidence": [], "impact": None, "confidence": 0.0,
                "insufficient_evidence": True, "reason": f"Agent's final answer was not valid JSON. Raw output: {text[:300]}",
                "_parse_failed": True}


def _invoke_with_timeout(graph, initial_state, recursion_limit, timeout_seconds):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(graph.invoke, initial_state, config={"recursion_limit": recursion_limit})
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"Investigation exceeded {timeout_seconds}s wall-clock limit")
    finally:
        executor.shutdown(wait=False)


def build_investigation_graph(llm, tools, db, company_id, incident_id):
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    def agent_node(state: InvestigationState):
        call_start = time.monotonic()
        response = llm_with_tools.invoke(state["messages"])
        latency_ms = round((time.monotonic() - call_start) * 1000)

        # Best-effort token usage extraction -- LangChain's standard attribute,
        # but NOT verified against a real Groq response in this build (no live
        # API access when this was written); logs gracefully as None if absent
        # rather than breaking the investigation over missing usage metadata.
        usage = getattr(response, "usage_metadata", None)
        will_call_tools = bool(getattr(response, "tool_calls", None))
        log_event(
            db, company_id, incident_id, ActorType.AGENT, "llm_call",
            f"LLM call ({'requesting tools' if will_call_tools else 'final answer'}), {latency_ms}ms",
            meta={"latency_ms": latency_ms, "token_usage": usage, "requested_tool_calls": will_call_tools},
        )
        return {"messages": [response]}

    def tools_node(state: InvestigationState):
        last: AIMessage = state["messages"][-1]
        tool_messages, trace_additions = [], []
        for call in last.tool_calls:
            tool = tools_by_name.get(call["name"])
            call_start = time.monotonic()
            result = {"error": f"Unknown tool '{call['name']}'"} if tool is None else tool.invoke(call["args"])
            latency_ms = round((time.monotonic() - call_start) * 1000)

            log_event(
                db, company_id, incident_id, ActorType.AGENT, "tool_call",
                f"{call['name']}({', '.join(f'{k}={v}' for k, v in call['args'].items())}), {latency_ms}ms",
                meta={"tool": call["name"], "args": call["args"], "latency_ms": latency_ms,
                      "result_summary": str(result)[:200]},
            )
            tool_messages.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"]))
            trace_additions.append({"tool": call["name"], "args": call["args"], "result": result})
        return {"messages": tool_messages, "tool_call_count": state["tool_call_count"] + len(last.tool_calls),
                "tool_trace": state["tool_trace"] + trace_additions}

    def force_end_node(state: InvestigationState):
        forced_messages = state["messages"] + [SystemMessage(content="You have reached the maximum number of tool calls allowed for this investigation. You no longer have access to any tools. Provide your final JSON answer now, using only the evidence already gathered above. If that evidence is insufficient, use the insufficient_evidence response shape.")]
        response = llm.invoke(forced_messages)
        return {"messages": [response]}

    def should_continue(state: InvestigationState):
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        if state["tool_call_count"] >= MAX_TOOL_CALLS:
            return "force_end"
        return "tools"

    graph = StateGraph(InvestigationState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("force_end", force_end_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END, "force_end": "force_end"})
    graph.add_edge("tools", "agent")
    graph.add_edge("force_end", END)
    return graph.compile()


def run_investigation(db: Session, company_id, incident: Incident) -> Investigation:
    tools = build_investigation_tools(db, company_id)
    llm = get_llm(temperature=0.0)
    graph = build_investigation_graph(llm, tools, db, company_id, incident.id)
    initial_state = {"messages": [SystemMessage(content=INVESTIGATION_SYSTEM_PROMPT), HumanMessage(content=_incident_summary(incident))],
                      "tool_call_count": 0, "tool_trace": []}
    start = time.monotonic()
    try:
        final_state = _invoke_with_timeout(graph, initial_state, RECURSION_LIMIT, MAX_WALL_SECONDS)
    except TimeoutError:
        return _save_investigation(db, company_id, incident, status=InvestigationStatus.FAILED, root_cause=None,
                                    evidence=[], impact=None, confidence=0.0, tool_calls=[],
                                    extra_note=f"Investigation exceeded the {MAX_WALL_SECONDS}s wall-clock guardrail.")
    except GraphRecursionError:
        return _save_investigation(db, company_id, incident, status=InvestigationStatus.FAILED, root_cause=None,
                                    evidence=[], impact=None, confidence=0.0, tool_calls=[],
                                    extra_note="Hit hard recursion limit -- MAX_TOOL_CALLS guardrail likely has a bug.")
    except Exception as e:
        return _save_investigation(db, company_id, incident, status=InvestigationStatus.FAILED, root_cause=None,
                                    evidence=[], impact=None, confidence=0.0, tool_calls=[],
                                    extra_note=f"Investigation raised an exception: {e}")

    elapsed = time.monotonic() - start
    parsed = parse_final_answer(final_state["messages"][-1].content)
    confidence = parsed.get("confidence")
    below_threshold = confidence is not None and confidence < CONFIDENCE_THRESHOLD

    if parsed.get("insufficient_evidence") or below_threshold:
        status = InvestigationStatus.INSUFFICIENT_EVIDENCE
        if below_threshold and not parsed.get("insufficient_evidence"):
            parsed["_confidence_override_reason"] = f"Confidence {confidence} is below the {CONFIDENCE_THRESHOLD} threshold; overriding to insufficient_evidence despite a stated root_cause."
    elif parsed.get("root_cause"):
        status = InvestigationStatus.COMPLETED
    else:
        status = InvestigationStatus.FAILED

    return _save_investigation(db, company_id, incident, status=status, root_cause=parsed.get("root_cause"),
                                evidence=parsed.get("evidence") or [], impact=parsed.get("impact"), confidence=parsed.get("confidence"),
                                tool_calls=final_state["tool_trace"],
                                extra_note=parsed.get("_confidence_override_reason") or parsed.get("reason"), elapsed_seconds=round(elapsed, 2))


def _save_investigation(db, company_id, incident, *, status, root_cause, evidence, impact, confidence, tool_calls, extra_note=None, elapsed_seconds=None):
    investigation = Investigation(company_id=company_id, incident_id=incident.id, status=status, root_cause=root_cause,
                                   evidence=evidence, impact=impact, confidence=confidence, tool_calls=tool_calls)
    db.add(investigation); db.flush()
    message = f"Investigation {status.value}: {len(tool_calls)} tool calls made."
    if root_cause: message += f" Root cause: {root_cause}"
    if extra_note: message += f" Note: {extra_note}"
    db.add(AuditLog(company_id=company_id, incident_id=incident.id, actor_type=ActorType.AGENT,
                     event_type="investigation_completed", message=message,
                     meta={"investigation_id": str(investigation.id), "tool_call_count": len(tool_calls), "confidence": confidence, "elapsed_seconds": elapsed_seconds}))
    db.commit(); db.refresh(investigation)
    return investigation