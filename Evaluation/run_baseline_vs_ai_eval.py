"""
Runs 19 scenarios (5 event types x 3-4 parameter variations each) through
BOTH the naive baseline system (app/services/baseline_service.py) and the
full AI pipeline (monitoring -> investigate -> decide -> optimize ->
approve -> execute -> verify), then reports the comparison table the
plan asks for.

USAGE (once you have a real GROQ_API_KEY configured):
    cd evaluation
    python run_baseline_vs_ai_eval.py

Makes real Groq API calls for the AI system side (2+ LLM calls per
scenario x 19 scenarios = 38+ calls minimum). No --fake flag, same
reasoning as run_scenario_tests.py: a harness that's easy to run fake
is a harness that quietly never gets run for real.

IMPORTANT HONESTY NOTE on metrics that need a real LLM to mean anything:
  - LLM Cost: computed from real token_usage in the audit log (Phase 23),
    using per-model Groq pricing below. Verify the GROQ_PRICING table
    against https://groq.com/pricing before trusting these numbers --
    it was written from memory and could be stale.
  - Investigation Accuracy is a PROXY (did the agent reach COMPLETED status,
    not "was the root cause actually correct" -- that would need
    human-graded ground truth this harness doesn't have).
"""
import json
import random
import sys
import time

from db import get_session

sys.path.insert(0, "../simulator")
from generator import generate_baseline, get_or_create_demo_company  # noqa: E402
from events import EVENT_REGISTRY  # noqa: E402

sys.path.insert(0, ".")
from run_scenario_tests import _touched_entity_ids, _resolve_indirect_entity_ids, find_caused_incident  # noqa: E402

from app.agents.decision import run_decision  # noqa: E402
from app.agents.investigation import run_investigation  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.enums import IncidentStatus, InvestigationStatus, RecommendationStatus  # noqa: E402
from app.models.recommendation import Recommendation  # noqa: E402
from app.optimization.or_tools_optimizer import optimize_options  # noqa: E402
from app.services.action_service import ActionError, execute_action  # noqa: E402
from app.services.baseline_service import apply_baseline_rule  # noqa: E402
from app.services.recommendation_service import RecommendationError, generate_explanation  # noqa: E402
from app.services.verification_service import VerificationError, verify_action  # noqa: E402
from app.monitoring.rules import run_all_checks  # noqa: E402
from app.agents.llm_client import get_llm  # noqa: E402

GROQ_PRICING = {
    "openai/gpt-oss-120b": {"input_per_million": 0.15, "output_per_million": 0.75},
}

EXPECTED_TOOLS_BY_TYPE = {
    "shipment_delay": {"get_shipment"}, "supplier_delay": {"get_supplier"},
    "inventory_shortage": {"get_inventory"}, "demand_spike": {"get_orders", "get_inventory"},
    "logistics_disruption": {"get_shipment", "get_warehouse"},
}


def build_scenarios():
    scenarios = []
    for delay in [2, 4, 6, 8]:
        scenarios.append({"id": f"shipment_delay_{delay}d", "event": "SHIPMENT_DELAY", "params": {"delay_days": delay}})
    for delay in [2, 4, 6, 8]:
        scenarios.append({"id": f"supplier_delay_{delay}d", "event": "SUPPLIER_DELAY", "params": {"delay_days": delay}})
    for i in range(4):
        scenarios.append({"id": f"inventory_shortage_{i}", "event": "INVENTORY_SHORTAGE", "params": {}})
    for i in range(4):
        scenarios.append({"id": f"demand_spike_{i}", "event": "DEMAND_SPIKE", "params": {}})
    for frac in [0.4, 0.6, 0.8]:
        scenarios.append({"id": f"logistics_disruption_{int(frac*100)}pct", "event": "LOGISTICS_DISRUPTION",
                           "params": {"delay_days": 5, "affected_fraction": frac}})
    return scenarios


def extract_llm_cost(db, company_id, incident_id, model: str):
    pricing = GROQ_PRICING.get(model)
    if pricing is None:
        return None
    entries = (db.query(AuditLog)
               .filter(AuditLog.company_id == company_id, AuditLog.incident_id == incident_id, AuditLog.event_type == "llm_call")
               .all())
    total_cost, found_any = 0.0, False
    for e in entries:
        usage = (e.meta or {}).get("token_usage")
        if not usage:
            continue
        found_any = True
        total_cost += usage.get("input_tokens", 0) / 1_000_000 * pricing["input_per_million"]
        total_cost += usage.get("output_tokens", 0) / 1_000_000 * pricing["output_per_million"]
    return total_cost if found_any else None


def extract_latency(db, company_id, incident_id):
    entries = (db.query(AuditLog)
               .filter(AuditLog.company_id == company_id, AuditLog.incident_id == incident_id,
                       AuditLog.event_type.in_(["llm_call", "tool_call"]))
               .all())
    total_ms = sum((e.meta or {}).get("latency_ms", 0) for e in entries)
    return round(total_ms / 1000, 2)


def check_stockout(db, company_id, incident):
    if not (incident.product_id and incident.warehouse_id):
        return False
    from app.models.operations import Inventory
    inv = (db.query(Inventory)
           .filter(Inventory.company_id == company_id, Inventory.product_id == incident.product_id,
                   Inventory.warehouse_id == incident.warehouse_id)
           .first())
    return inv is not None and inv.quantity_on_hand <= 0


def run_baseline_branch(db, company, scenario):
    trigger_fn = EVENT_REGISTRY[scenario["event"]]
    event_result = trigger_fn(db, company.id, **scenario["params"])
    run_all_checks(db, company.id)
    direct_ids = _touched_entity_ids(event_result)
    indirect_ids = _resolve_indirect_entity_ids(db, direct_ids)
    incident = find_caused_incident(db, company.id, set(), direct_ids, indirect_ids)
    if incident is None:
        return {"scenario_id": scenario["id"], "resolved": False, "cost": 0, "resolution_time_s": 0, "stockout": True}

    t0 = time.monotonic()
    result = apply_baseline_rule(db, company.id, incident)
    elapsed = round(time.monotonic() - t0, 3)
    stockout = check_stockout(db, company.id, incident) if not result["resolved"] else False

    return {"scenario_id": scenario["id"], "resolved": result["resolved"], "cost": result["estimated_cost"],
            "resolution_time_s": elapsed, "stockout": stockout}


def run_ai_branch(db, company, scenario):
    trigger_fn = EVENT_REGISTRY[scenario["event"]]
    event_result = trigger_fn(db, company.id, **scenario["params"])
    run_all_checks(db, company.id)
    direct_ids = _touched_entity_ids(event_result)
    indirect_ids = _resolve_indirect_entity_ids(db, direct_ids)
    incident = find_caused_incident(db, company.id, set(), direct_ids, indirect_ids)
    if incident is None:
        return {"scenario_id": scenario["id"], "resolved": False, "cost": None, "resolution_time_s": None,
                "stockout": True, "investigation_completed": False, "abstained": False, "used_expected_tool": None,
                "llm_cost": None, "latency_s": None}

    t0 = time.monotonic()
    incident.status = IncidentStatus.INVESTIGATING
    db.commit(); db.refresh(incident)

    investigation = run_investigation(db, company.id, incident)
    investigation_completed = investigation.status == InvestigationStatus.COMPLETED
    abstained = investigation.status == InvestigationStatus.INSUFFICIENT_EVIDENCE
    tools_called = {t["tool"] for t in (investigation.tool_calls or [])}
    expected_tools = EXPECTED_TOOLS_BY_TYPE.get(incident.type.value, set())
    used_expected_tool = bool(tools_called & expected_tools) if expected_tools else None

    resolved, cost = False, None
    if investigation_completed:
        try:
            decision_result = run_decision(db, company.id, incident, investigation)
            if decision_result["status"] == "completed" and decision_result["options"]:
                optimization_result = optimize_options(decision_result["options"], severity=incident.severity.value)
                options_by_name = {o.get("option"): o for o in decision_result["options"]}
                merged = [{**options_by_name.get(s["option"], {}), **s} for s in optimization_result["scores"]]
                llm = get_llm(temperature=0.3)
                explanation = generate_explanation(llm, incident, investigation, optimization_result)
                chosen = optimization_result["chosen_option"]
                recommendation = Recommendation(
                    company_id=company.id, incident_id=incident.id, investigation_id=investigation.id,
                    option_chosen=chosen.get("option"), options_considered=merged,
                    estimated_cost=chosen.get("estimated_cost"), expected_delay_days=chosen.get("expected_delay_days"),
                    stockout_risk=chosen.get("stockout_risk"), reasoning=explanation,
                    confidence=decision_result["confidence"], status=RecommendationStatus.PENDING,
                )
                db.add(recommendation)
                incident.status = IncidentStatus.RECOMMENDED
                db.commit(); db.refresh(recommendation)

                # Eval harness auto-approves -- there is no human in a 19-scenario batch
                # run. This bypass is ONLY for evaluation; the real API always requires
                # Phase 18's human approval endpoint.
                recommendation.status = RecommendationStatus.APPROVED
                incident.status = IncidentStatus.APPROVED
                db.commit()

                try:
                    action = execute_action(db, company.id, recommendation)
                    verified = verify_action(db, company.id, action)
                    resolved = verified.verification_result.value == "success"
                    cost = recommendation.estimated_cost
                except ActionError:
                    resolved = False
        except RecommendationError:
            resolved = False

    elapsed = round(time.monotonic() - t0, 3)
    stockout = check_stockout(db, company.id, incident) if not resolved else False
    llm_cost = extract_llm_cost(db, company.id, incident.id, "openai/gpt-oss-120b")
    latency = extract_latency(db, company.id, incident.id)

    return {"scenario_id": scenario["id"], "resolved": resolved, "cost": cost, "resolution_time_s": elapsed,
            "stockout": stockout, "investigation_completed": investigation_completed, "abstained": abstained,
            "used_expected_tool": used_expected_tool, "llm_cost": llm_cost, "latency_s": latency}


def aggregate(results, is_ai):
    n = len(results)
    resolved_count = sum(1 for r in results if r["resolved"])
    stockout_count = sum(1 for r in results if r["stockout"])
    costs = [r["cost"] for r in results if r["resolved"] and r["cost"] is not None]
    times = [r["resolution_time_s"] for r in results if r["resolution_time_s"] is not None]

    summary = {
        "scenarios": n,
        "resolution_rate": round(resolved_count / n * 100, 1) if n else 0,
        "stockout_events": stockout_count,
        "avg_cost": round(sum(costs) / len(costs), 2) if costs else None,
        "avg_resolution_time_s": round(sum(times) / len(times), 3) if times else None,
    }
    if is_ai:
        inv_completed = [r for r in results if r.get("investigation_completed") is not None]
        abstained = [r for r in results if r.get("abstained")]
        tool_checks = [r for r in results if r.get("used_expected_tool") is not None]
        tool_correct = [r for r in tool_checks if r["used_expected_tool"]]
        llm_costs = [r["llm_cost"] for r in results if r.get("llm_cost") is not None]
        latencies = [r["latency_s"] for r in results if r.get("latency_s") is not None]
        summary.update({
            "investigation_accuracy_pct": round(sum(1 for r in inv_completed if r["investigation_completed"]) / len(inv_completed) * 100, 1) if inv_completed else None,
            "tool_selection_accuracy_pct": round(len(tool_correct) / len(tool_checks) * 100, 1) if tool_checks else None,
            "abstention_rate_pct": round(len(abstained) / n * 100, 1) if n else None,
            "avg_llm_cost_usd": round(sum(llm_costs) / len(llm_costs), 6) if llm_costs else None,
            "llm_cost_note": None if llm_costs else "No token_usage recorded (fake LLM in this run, or model omitted usage_metadata)",
            "avg_latency_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
        })
    return summary


def print_comparison_table(baseline_summary, ai_summary):
    print("\n" + "=" * 70)
    print(f"{'Metric':<28}{'Baseline':<20}{'AI System':<20}")
    print("=" * 70)
    print(f"{'Resolution Rate':<28}{str(baseline_summary['resolution_rate'])+'%':<20}{str(ai_summary['resolution_rate'])+'%':<20}")
    print(f"{'Stockout Events':<28}{baseline_summary['stockout_events']:<20}{ai_summary['stockout_events']:<20}")
    print(f"{'Avg Cost':<28}{'$'+str(baseline_summary['avg_cost']) if baseline_summary['avg_cost'] else 'n/a':<20}{'$'+str(ai_summary['avg_cost']) if ai_summary['avg_cost'] else 'n/a':<20}")
    print(f"{'Avg Resolution Time':<28}{str(baseline_summary['avg_resolution_time_s'])+'s':<20}{str(ai_summary['avg_resolution_time_s'])+'s':<20}")
    print("-" * 70)
    print(f"{'Investigation Accuracy':<28}{'n/a':<20}{str(ai_summary.get('investigation_accuracy_pct'))+'%':<20}")
    print(f"{'Tool Selection Accuracy':<28}{'n/a':<20}{str(ai_summary.get('tool_selection_accuracy_pct'))+'%':<20}")
    print(f"{'Abstention Rate':<28}{'n/a':<20}{str(ai_summary.get('abstention_rate_pct'))+'%':<20}")
    llm_cost_display = ('$' + str(ai_summary['avg_llm_cost_usd'])) if ai_summary.get('avg_llm_cost_usd') else ai_summary.get('llm_cost_note', 'n/a')
    print(f"{'Avg LLM Cost':<28}{'n/a':<20}{llm_cost_display:<20}")
    print(f"{'Avg Latency':<28}{'n/a (no LLM)':<20}{str(ai_summary.get('avg_latency_s'))+'s':<20}")
    print("=" * 70)


def main():
    db = get_session()
    scenarios = build_scenarios()
    baseline_results, ai_results = [], []

    for i, scenario in enumerate(scenarios):
        print(f"[{i+1}/{len(scenarios)}] {scenario['id']}")

        random.seed(i)
        baseline_company = get_or_create_demo_company(db, f"Eval Baseline - {scenario['id']}")
        generate_baseline(db, baseline_company.id)
        baseline_results.append(run_baseline_branch(db, baseline_company, scenario))

        random.seed(i)
        ai_company = get_or_create_demo_company(db, f"Eval AI - {scenario['id']}")
        generate_baseline(db, ai_company.id)
        ai_results.append(run_ai_branch(db, ai_company, scenario))

    baseline_summary = aggregate(baseline_results, is_ai=False)
    ai_summary = aggregate(ai_results, is_ai=True)
    print_comparison_table(baseline_summary, ai_summary)

    with open("baseline_vs_ai_results.json", "w") as f:
        json.dump({"baseline_results": baseline_results, "ai_results": ai_results,
                    "baseline_summary": baseline_summary, "ai_summary": ai_summary}, f, indent=2, default=str)
    print("\nFull results written to evaluation/baseline_vs_ai_results.json")
    db.close()


if __name__ == "__main__":
    main()