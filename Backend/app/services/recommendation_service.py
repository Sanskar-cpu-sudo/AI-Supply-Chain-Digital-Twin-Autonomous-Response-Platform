"""
Combines:
    Investigation (already completed, Phase 12)
        -> Decision Agent (Phase 15: propose options)
        -> Optimization (Phase 16: OR-Tools picks the winner, deterministically)
        -> Recommendation (this file: persist it + a plain-language explanation)

Per the plan: "LLM -> understanding + reasoning + explanation. OR-Tools ->
actual optimization." The LLM here never picks the option -- it only
explains a decision OR-Tools already made.
"""
from app.agents.decision import run_decision
from app.agents.llm_client import get_llm
from app.models.enums import IncidentStatus, RecommendationStatus
from app.models.incident import Incident
from app.models.investigation import Investigation
from app.models.recommendation import Recommendation
from app.optimization.or_tools_optimizer import optimize_options
from app.prompts.recommendation_prompt import build_explanation_prompt


class RecommendationError(Exception):
    """Raised when no viable recommendation can be produced (e.g. the
    Decision Agent couldn't propose any usable options). Callers (the
    route) should surface this as a clear 4xx, not a 500 -- it's an
    expected outcome, not a bug, when evidence is genuinely insufficient."""


def generate_explanation(llm, incident: Incident, investigation: Investigation, optimization_result: dict) -> str:
    prompt = build_explanation_prompt(incident, investigation, optimization_result)
    response = llm.invoke(prompt)
    return response.content.strip()


def generate_recommendation(db, company_id, incident: Incident, investigation: Investigation) -> Recommendation:
    """
    Runs Decision Agent -> Optimization -> Explanation and persists the
    result as a Recommendation row. Also advances the incident to
    RECOMMENDED status (Phase 18's human approval step comes next).

    Raises RecommendationError if the Decision Agent couldn't produce
    any viable options -- there is nothing for OR-Tools to optimize over
    in that case, and fabricating a Recommendation would be worse than
    surfacing the gap for human review.
    """
    decision_result = run_decision(db, company_id, incident, investigation)

    if decision_result["status"] != "completed" or not decision_result["options"]:
        raise RecommendationError(
            f"Decision agent could not produce viable options (status: {decision_result['status']}, "
            f"reason: {decision_result.get('reason')}). Human review required before a recommendation "
            f"can be made."
        )

    optimization_result = optimize_options(decision_result["options"], severity=incident.severity.value)

    # IMPORTANT: merge each original Decision Agent option (rationale, evidence,
    # execution_data -- e.g. target_supplier_id) with its OR-Tools score, by
    # matching on the "option" key. Storing ONLY optimization_result["scores"]
    # here would silently discard execution_data, which Phase 19's Action
    # Service needs to actually carry out the chosen option -- caught by
    # tracing through what Phase 19 needs before writing it.
    options_by_name = {opt.get("option"): opt for opt in decision_result["options"]}
    merged_options_considered = [
        {**options_by_name.get(score["option"], {}), **score}
        for score in optimization_result["scores"]
    ]

    llm = get_llm(temperature=0.3)  # slightly above 0 -- explanatory prose benefits from a little
    # natural variation, unlike the investigation/decision agents' diagnostic reasoning which stays at 0.
    explanation = generate_explanation(llm, incident, investigation, optimization_result)

    chosen = optimization_result["chosen_option"]
    recommendation = Recommendation(
        company_id=company_id,
        incident_id=incident.id,
        investigation_id=investigation.id,
        option_chosen=chosen.get("option"),
        options_considered=merged_options_considered,
        estimated_cost=chosen.get("estimated_cost"),
        expected_delay_days=chosen.get("expected_delay_days"),
        stockout_risk=chosen.get("stockout_risk"),
        reasoning=explanation,
        confidence=decision_result["confidence"],
        status=RecommendationStatus.PENDING,
    )
    db.add(recommendation)

    incident.status = IncidentStatus.RECOMMENDED
    db.commit()
    db.refresh(recommendation)
    return recommendation