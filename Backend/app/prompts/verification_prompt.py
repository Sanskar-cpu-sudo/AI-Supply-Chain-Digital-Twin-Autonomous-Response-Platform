"""
Prompt for explaining a verification outcome in plain language. Like
recommendation_prompt.py, this is deliberately NOT a tool-calling agent:
the success/failure determination is made deterministically (see
verification_service.py's determine_success), by comparing before/after
snapshots that are already fully known. The LLM's only job is to narrate
that comparison the way the plan's own example does:

    {"success": true, "reason": "Inventory recovered and affected orders
    are no longer at risk."}

Giving this step tool access would risk it re-litigating a comparison
that's already been made correctly by code.
"""


def build_verification_explanation_prompt(incident, action, before: dict, after: dict, success: bool) -> str:
    return f"""\
You are writing a short, plain-language explanation of whether a recently
executed supply chain action actually solved the problem it was meant to fix.

Incident: {incident.type.value}, severity {incident.severity.value}
Action taken: {action.action_type}
Action result: {action.result}

BEFORE the action:
{before}

AFTER the action:
{after}

Deterministic verdict (already decided, do not second-guess it): {"SUCCESS" if success else "FAILED"}

Write a 1-2 sentence explanation of why this outcome is a {"success" if success else "failure"},
referencing the specific before/after numbers above. Do not invent any facts not present above.
Respond with ONLY the explanation text, no preamble, no JSON, no markdown formatting.
"""