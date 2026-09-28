import concurrent.futures
import json
import time
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from sqlalchemy.orm import Session

from app.agents.llm_client import get_llm
from app.models.audit_log import AuditLog
from app.models.enums import ActorType
from app.models.incident import Incident
from app.models.investigation import Investigation
from app.prompts.decision_prompt import DECISION_SYSTEM_PROMPT
from app.services.audit_log_service import log_event
from app.tools.registry import build_investigation_tools

MAX_TOOL_CALLS = 8
RECURSION_LIMIT = 30
MAX_WALL_SECONDS = 60
CONFIDENCE_THRESHOLD = 0.5
MIN_OPTIONS_EXPECTED = 2


class DecisionState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_call_count: int
    tool_trace: list


def _decision_input_summary(incident: Incident, investigation: Investigation) -> str:
    lines = [
        f"Incident Type: {incident.type.value}", f"Severity: {incident.severity.value}",
        f"Description: {incident.description or '(none provided)'}", "",
        "=== Completed Investigation (the 'why' is already known) ===",
        f"Root cause: {investigation.root_cause}", f"Evidence: {investigation.evidence}", f"Impact: {investigation.impact}", "",
        "Known linked entity ids (use these directly with your tools -- do not guess ids):",
        f"- shipment_id: {incident.shipment_id or 'unknown'}", f"- supplier_id: {incident.supplier_id or 'unknown'}",
        f"- product_id: {incident.product_id or 'unknown'}", f"- warehouse_id: {incident.warehouse_id or 'unknown'}",
        "", "Propose response options now.",
    ]
    return "\n".join(lines)


def parse_decision_output(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"options": [], "confidence": 0.0, "insufficient_evidence": True,
                "reason": f"Agent's final answer was not valid JSON. Raw output: {text[:300]}", "_parse_failed": True}


def _invoke_with_timeout(graph, initial_state, recursion_limit, timeout_seconds):
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(graph.invoke, initial_state, config={"recursion_limit": recursion_limit})
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"Decision agent exceeded {timeout_seconds}s wall-clock limit")
    finally:
        executor.shutdown(wait=False)


def build_decision_graph(llm, tools, db, company_id, incident_id):
    llm_with_tools = llm.bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    def agent_node(state: DecisionState):
        call_start = time.monotonic()
        response = llm_with_tools.invoke(state["messages"])
        latency_ms = round((time.monotonic() - call_start) * 1000)
        usage = getattr(response, "usage_metadata", None)
        will_call_tools = bool(getattr(response, "tool_calls", None))
        log_event(
            db, company_id, incident_id, ActorType.AGENT, "llm_call",
            f"Decision LLM call ({'requesting tools' if will_call_tools else 'final answer'}), {latency_ms}ms",
            meta={"latency_ms": latency_ms, "token_usage": usage, "requested_tool_calls": will_call_tools},
        )
        return {"messages": [response]}

    def tools_node(state: DecisionState):
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

    def force_end_node(state: DecisionState):
        forced_messages = state["messages"] + [SystemMessage(content="You have reached the maximum number of tool calls allowed. You no longer have access to any tools. Provide your final JSON answer now, using only the evidence already gathered above.")]
        response = llm.invoke(forced_messages)
        return {"messages": [response]}

    def should_continue(state: DecisionState):
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        if state["tool_call_count"] >= MAX_TOOL_CALLS:
            return "force_end"
        return "tools"

    graph = StateGraph(DecisionState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("force_end", force_end_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END, "force_end": "force_end"})
    graph.add_edge("tools", "agent")
    graph.add_edge("force_end", END)
    return graph.compile()


def run_decision(db: Session, company_id, incident: Incident, investigation: Investigation) -> dict:
    tools = build_investigation_tools(db, company_id)
    llm = get_llm(temperature=0.0)
    graph = build_decision_graph(llm, tools, db, company_id, incident.id)
    initial_state = {"messages": [SystemMessage(content=DECISION_SYSTEM_PROMPT), HumanMessage(content=_decision_input_summary(incident, investigation))],
                      "tool_call_count": 0, "tool_trace": []}
    start = time.monotonic()
    try:
        final_state = _invoke_with_timeout(graph, initial_state, RECURSION_LIMIT, MAX_WALL_SECONDS)
    except TimeoutError:
        return _finalize(db, incident, status="failed", options=[], confidence=0.0, tool_calls=[], reason=f"Exceeded {MAX_WALL_SECONDS}s wall-clock guardrail.")
    except GraphRecursionError:
        return _finalize(db, incident, status="failed", options=[], confidence=0.0, tool_calls=[], reason="Hit hard recursion limit.")
    except Exception as e:
        return _finalize(db, incident, status="failed", options=[], confidence=0.0, tool_calls=[], reason=f"Decision agent raised an exception: {e}")

    elapsed = round(time.monotonic() - start, 2)
    parsed = parse_decision_output(final_state["messages"][-1].content)
    confidence = parsed.get("confidence")
    below_threshold = confidence is not None and confidence < CONFIDENCE_THRESHOLD
    options = parsed.get("options") or []
    status = "insufficient_evidence" if (parsed.get("insufficient_evidence") or below_threshold or not options) else "completed"
    return _finalize(db, incident, status=status, options=options, confidence=confidence, tool_calls=final_state["tool_trace"], reason=parsed.get("reason"), elapsed_seconds=elapsed)


def _finalize(db, incident, *, status, options, confidence, tool_calls, reason=None, elapsed_seconds=None):
    message = f"Decision agent {status}: {len(options)} option(s) proposed, {len(tool_calls)} tool calls."
    if reason: message += f" Note: {reason}"
    if status == "completed" and len(options) < MIN_OPTIONS_EXPECTED:
        message += f" (WARNING: fewer than {MIN_OPTIONS_EXPECTED} options.)"
    db.add(AuditLog(company_id=incident.company_id, incident_id=incident.id, actor_type=ActorType.AGENT,
                     event_type="decision_completed", message=message,
                     meta={"option_count": len(options), "confidence": confidence, "elapsed_seconds": elapsed_seconds}))
    db.commit()
    return {"status": status, "options": options, "confidence": confidence, "tool_calls": tool_calls, "reason": reason}