"""
Deterministic option selection using OR-Tools' CP-SAT solver. No LLM
anywhere in this file, per the plan: "you should not let the LLM do
everything ... use algorithms/optimization to evaluate options."

Why CP-SAT and not just `min(options, key=weighted_score)`: a plain
weighted-sum comparison can't cleanly express a HARD business rule like
"never pick a high-stockout-risk option for a critical-severity incident,
unless every option carries that risk." Encoding that as nested if/else
gets unwieldy fast as more rules get added later. CP-SAT lets us state
it as an actual constraint the solver must respect, separate from the
soft weighted-preference objective -- this is what "real optimization"
buys over sorting, even though these problems are tiny (2-4 boolean
variables) and computational scale is not the point here.

CP-SAT requires INTEGER coefficients in its objective (no native floats),
so normalized 0-1 scores are scaled up before being handed to the solver
-- see _to_int_coefficient.
"""
from ortools.sat.python import cp_model

STOCKOUT_RISK_SCORE = {"low": 0.0, "medium": 0.5, "high": 1.0}

DEFAULT_WEIGHTS = {"cost": 0.4, "delay": 0.3, "stockout": 0.3}

# CP-SAT needs integer objective coefficients; this just controls precision
# (higher = more decimal precision preserved when scores are scaled up).
_INT_SCALE = 10_000


def _to_int_coefficient(normalized_value: float) -> int:
    return max(0, round(normalized_value * _INT_SCALE))


def _normalize(values: list[float]) -> list[float]:
    """Scale a list of non-negative values to 0-1 by dividing by the max.
    All-zero input (e.g. every option costs $0) returns all zeros rather
    than dividing by zero."""
    max_value = max(values) if values else 0
    if max_value == 0:
        return [0.0 for _ in values]
    return [v / max_value for v in values]


def optimize_options(options: list[dict], severity: str, weights: dict | None = None) -> dict:
    """
    options: the Decision Agent's proposed options (Phase 15's output),
             each expected to have estimated_cost, expected_delay_days,
             stockout_risk ("low"/"medium"/"high").
    severity: the incident's severity -- drives the hard constraint.

    Returns:
    {
        "chosen_index": int,
        "chosen_option": dict (the winning option, unchanged from input),
        "scores": [{"option": str, "normalized_cost": float, "normalized_delay": float,
                    "stockout_score": float, "weighted_score": float, "excluded_by_constraint": bool}, ...],
        "constraint_applied": bool,   -- whether the critical-severity stockout exclusion actually fired
        "solver_status": str,
    }

    Raises ValueError if options is empty -- there is nothing to optimize
    over, and returning a fabricated "chosen option" would be worse than
    failing loudly.
    """
    if not options:
        raise ValueError("optimize_options requires at least one option to choose from")

    weights = weights or DEFAULT_WEIGHTS

    costs = [float(o.get("estimated_cost") or 0) for o in options]
    delays = [float(o.get("expected_delay_days") or 0) for o in options]
    stockout_scores = [STOCKOUT_RISK_SCORE.get(o.get("stockout_risk", "medium"), 0.5) for o in options]

    norm_costs = _normalize(costs)
    norm_delays = _normalize(delays)
    # stockout_scores are already 0-1 by construction, no normalization needed

    weighted_scores = [
        weights["cost"] * norm_costs[i] + weights["delay"] * norm_delays[i] + weights["stockout"] * stockout_scores[i]
        for i in range(len(options))
    ]

    # The hard constraint only makes sense if it wouldn't eliminate every
    # option -- if literally everything is high stockout risk, there's no
    # alternative to enforce a preference for.
    high_stockout_flags = [o.get("stockout_risk") == "high" for o in options]
    constraint_applies = severity == "critical" and any(high_stockout_flags) and not all(high_stockout_flags)

    model = cp_model.CpModel()
    chosen = [model.NewBoolVar(f"chosen_{i}") for i in range(len(options))]
    model.Add(sum(chosen) == 1)  # exactly one option must be selected

    if constraint_applies:
        for i, is_high_risk in enumerate(high_stockout_flags):
            if is_high_risk:
                model.Add(chosen[i] == 0)

    model.Minimize(sum(_to_int_coefficient(weighted_scores[i]) * chosen[i] for i in range(len(options))))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Should not happen given the "not all high-risk" guard above, but
        # never silently return a wrong answer -- fall back to the
        # unconstrained model rather than raise, since we still owe the
        # caller SOME answer.
        model_fallback = cp_model.CpModel()
        chosen_fb = [model_fallback.NewBoolVar(f"chosen_{i}") for i in range(len(options))]
        model_fallback.Add(sum(chosen_fb) == 1)
        model_fallback.Minimize(
            sum(_to_int_coefficient(weighted_scores[i]) * chosen_fb[i] for i in range(len(options)))
        )
        solver = cp_model.CpSolver()
        status = solver.Solve(model_fallback)
        chosen_index = next(i for i in range(len(options)) if solver.Value(chosen_fb[i]) == 1)
        constraint_applies = False  # the constrained version was infeasible, so it didn't actually apply
    else:
        chosen_index = next(i for i in range(len(options)) if solver.Value(chosen[i]) == 1)

    scores = [
        {
            "option": options[i].get("option"),
            "normalized_cost": round(norm_costs[i], 3),
            "normalized_delay": round(norm_delays[i], 3),
            "stockout_score": round(stockout_scores[i], 3),
            "weighted_score": round(weighted_scores[i], 3),
            "excluded_by_constraint": constraint_applies and high_stockout_flags[i],
        }
        for i in range(len(options))
    ]

    return {
        "chosen_index": chosen_index,
        "chosen_option": options[chosen_index],
        "scores": scores,
        "constraint_applied": constraint_applies,
        "solver_status": solver.StatusName(status),
    }