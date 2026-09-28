"""
Prompt for the plain-language explanation of an already-decided
recommendation. This is deliberately NOT a tool-calling agent -- the
option was already chosen deterministically by OR-Tools (Phase 16); the
LLM's only job is to explain that decision in plain English, the way
the plan's own example does:

    "Supplier B is recommended because it avoids the projected stockout
    while having lower incremental cost than the alternate route."

The LLM must not re-derive or second-guess the numbers -- just narrate
them. Giving it tool access here would risk it "helpfully" contradicting
the optimizer's actual decision.
"""


def build_explanation_prompt(incident, investigation, optimization_result: dict) -> str:
    chosen = optimization_result["chosen_option"]
    scores = optimization_result["scores"]
    constraint_note = (
        "\nNote: a hard safety constraint excluded one or more high-stockout-risk options "
        "for this critical-severity incident, regardless of their cost." if optimization_result["constraint_applied"] else ""
    )

    return f"""\
You are writing a short, plain-language explanation for a supply chain manager
who needs to quickly understand why a specific response was recommended.

Incident: {incident.type.value}, severity {incident.severity.value}
Root cause (from investigation): {investigation.root_cause}
Impact: {investigation.impact}

Options considered and their scores (lower weighted_score = more favorable):
{scores}
{constraint_note}
CHOSEN OPTION: {chosen.get('option')}
  Estimated cost: ${chosen.get('estimated_cost')}
  Expected delay: {chosen.get('expected_delay_days')} days
  Stockout risk: {chosen.get('stockout_risk')}

Write a 1-3 sentence explanation of why this option was chosen over the
others, referencing the actual numbers above. Do not invent any facts not
present above. Do not re-evaluate or second-guess the choice -- it has
already been made; your only job is to explain it clearly. Respond with
ONLY the explanation text, no preamble, no JSON, no markdown formatting.
"""