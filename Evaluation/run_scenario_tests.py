"""
Runs every scenario in simulator/scenarios/scenarios.json through the
real pipeline. See Phase 13 delivery notes for full design rationale.
"""
import json
import sys
import time

from db import get_session

sys.path.insert(0, "../simulator")
from generator import generate_baseline, get_or_create_demo_company  # noqa: E402
from events import EVENT_REGISTRY  # noqa: E402

from app.agents.investigation import run_investigation  # noqa: E402
from app.models.enums import IncidentStatus, IncidentType  # noqa: E402
from app.models.incident import Incident  # noqa: E402
from app.monitoring.rules import run_all_checks  # noqa: E402

EVAL_COMPANY_NAME = "Eval Test Co"

EXPECTED_TOOLS_BY_TYPE = {
    "shipment_delay": {"get_shipment"}, "supplier_delay": {"get_supplier"},
    "inventory_shortage": {"get_inventory"}, "demand_spike": {"get_orders", "get_inventory"},
    "logistics_disruption": {"get_shipment", "get_warehouse"},
}


def load_scenarios():
    with open("../simulator/scenarios/scenarios.json") as f:
        return json.load(f)["scenarios"]


def _touched_entity_ids(event_result: dict) -> set:
    """Extract every entity id the triggered event actually touched, so we
    can tie the resulting incident back to THIS event rather than to
    unrelated background noise the same monitoring pass also detects."""
    ids = set()
    for key, value in event_result.items():
        if key.endswith("_id") and isinstance(value, str):
            ids.add(value)
        if key == "shipments_affected" and isinstance(value, list):
            ids.update(value)
    return ids


def _resolve_indirect_entity_ids(db, touched_ids: set) -> set:
    """Resolve touched shipment ids to their actual supplier/product/warehouse,
    so an incident that groups by supplier (no shipment_id set) still matches."""
    from app.models.operations import Shipment
    import uuid as _uuid
    extra = set()
    for tid in touched_ids:
        try:
            shipment = db.get(Shipment, _uuid.UUID(tid))
        except (ValueError, TypeError):
            continue
        if shipment is not None:
            extra.update(str(x) for x in (shipment.supplier_id, shipment.product_id, shipment.warehouse_id) if x)
    return extra


def find_caused_incident(db, company_id, exclude_ids: set, direct_ids: set, indirect_ids: set):
    """Among newly-created OPEN incidents, prefer one whose linked entities
    overlap with direct_ids (from the event itself) over indirect_ids
    (resolved indirectly) -- direct matches are a stronger causal signal."""
    candidates = (
        db.query(Incident)
        .filter(Incident.company_id == company_id, Incident.status == IncidentStatus.OPEN,
                ~Incident.id.in_(exclude_ids) if exclude_ids else True)
        .order_by(Incident.created_at.desc())
        .all()
    )
    if not candidates:
        return None

    def linked_ids(incident):
        return {str(incident.shipment_id) if incident.shipment_id else None,
                str(incident.supplier_id) if incident.supplier_id else None,
                str(incident.product_id) if incident.product_id else None,
                str(incident.warehouse_id) if incident.warehouse_id else None}

    if direct_ids:
        for incident in candidates:
            if linked_ids(incident) & direct_ids:
                return incident
    if indirect_ids:
        for incident in candidates:
            if linked_ids(incident) & indirect_ids:
                return incident
    if not direct_ids and not indirect_ids:
        return candidates[0]
    return None


def run_one_scenario(db, company, scenario: dict) -> dict:
    existing_incident_ids = {i.id for i in db.query(Incident.id).filter(Incident.company_id == company.id)}
    trigger_fn = EVENT_REGISTRY[scenario["event"]]
    event_result = trigger_fn(db, company.id, **scenario["params"])
    monitoring_summary = run_all_checks(db, company.id)
    monitoring_summary.pop("created_incidents", None)  # raw ORM objects, not JSON-safe for this report

    direct_ids = _touched_entity_ids(event_result)
    indirect_ids = _resolve_indirect_entity_ids(db, direct_ids)
    incident = find_caused_incident(db, company.id, existing_incident_ids, direct_ids, indirect_ids)
    if incident is None:
        return {"scenario_id": scenario["id"], "result": "NO_INCIDENT_CREATED",
                "event_result": event_result, "monitoring_summary": monitoring_summary}

    type_matched_expectation = incident.type.value == scenario["expected_incident_type"]
    incident.status = IncidentStatus.INVESTIGATING
    db.commit(); db.refresh(incident)

    t0 = time.monotonic()
    investigation = run_investigation(db, company.id, incident)
    elapsed = round(time.monotonic() - t0, 2)

    tools_called = {t["tool"] for t in (investigation.tool_calls or [])}
    expected_tools = EXPECTED_TOOLS_BY_TYPE.get(incident.type.value, set())
    used_expected_tool = bool(tools_called & expected_tools) if expected_tools else None

    return {"scenario_id": scenario["id"], "result": "RAN", "incident_id": str(incident.id),
            "incident_type": incident.type.value, "expected_incident_type": scenario["expected_incident_type"],
            "type_matched_expectation": type_matched_expectation, "event_result": event_result,
            "investigation_status": investigation.status.value, "confidence": investigation.confidence,
            "root_cause": investigation.root_cause, "evidence": investigation.evidence, "impact": investigation.impact,
            "tool_call_count": len(investigation.tool_calls or []), "tools_called": sorted(tools_called),
            "expected_tools": sorted(expected_tools), "used_expected_tool": used_expected_tool,
            "elapsed_seconds": elapsed, "full_tool_trace": investigation.tool_calls}


def main():
    db = get_session()
    company = get_or_create_demo_company(db, EVAL_COMPANY_NAME)
    generate_baseline(db, company.id)
    scenarios = load_scenarios()
    results = []
    for scenario in scenarios:
        print(f"Running {scenario['id']}...")
        results.append(run_one_scenario(db, company, scenario))
    with open("last_run_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print("Done. Results written to evaluation/last_run_results.json")
    db.close()


if __name__ == "__main__":
    main()