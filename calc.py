"""Deterministic screening score: min-max normalise each KPI across the candidate set, weight, sum.

score = 100 * sum(|w_k| * norm_k) where norm_k is the airport's min-max position for KPI k across
the candidates (a negative weight flips it: lower is better). Weights are normalised to sum to 1.
"""

KPIS = ("pax_growth", "load_factor", "seat_growth", "scale", "intl_share", "delay")

PRESETS = {
    # Where would added terminal/flight capacity be used: growth, full planes, seats already added,
    # size, and current strain.
    "expansion": {"pax_growth": 0.30, "load_factor": 0.20, "seat_growth": 0.20, "scale": 0.15, "delay": 0.15},
    # How stressed is the airport right now: full planes, active delays, size.
    "congestion": {"load_factor": 0.40, "delay": 0.40, "scale": 0.20},
    # Demand outrunning supply: full planes, delays, passenger growth, and seats NOT keeping up.
    "unmet_demand": {"load_factor": 0.35, "delay": 0.25, "pax_growth": 0.25, "seat_growth": -0.15},
}


def _normalise_weights(weights: dict) -> dict:
    total = sum(abs(w) for w in weights.values())
    if total == 0:
        raise ValueError("weights sum to zero")
    return {k: w / total for k, w in weights.items() if w != 0}


def score_airports(kpis: dict, objective: str = "expansion", weights: dict | None = None) -> dict:
    """`kpis` = {code: {kpi_name: value}}. Returns ranking with the arithmetic per airport."""
    if weights is None:
        if objective not in PRESETS:
            return {"error": f"unknown objective {objective!r}; use one of {sorted(PRESETS)}"}
        weights = PRESETS[objective]
    unknown = [k for k in weights if k not in KPIS]
    if unknown:
        return {"error": f"unknown KPI(s) in weights: {unknown}; known: {list(KPIS)}"}
    try:
        w = _normalise_weights({k: float(v) for k, v in weights.items()})
    except (TypeError, ValueError) as e:
        return {"error": f"bad weights: {e}"}

    # Only airports with every weighted KPI present are scored.
    scored, not_scored = {}, {}
    for code, vals in kpis.items():
        missing = [k for k in w if vals.get(k) is None]
        if missing:
            not_scored[code] = f"missing {', '.join(missing)}"
        else:
            scored[code] = {k: float(vals[k]) for k in w}
    if len(scored) < 2:
        return {
            "error": "need at least 2 airports with complete KPIs to score (min-max is relative); "
            "add peer airports",
            "not_scored": not_scored,
        }

    lo = {k: min(v[k] for v in scored.values()) for k in w}
    hi = {k: max(v[k] for v in scored.values()) for k in w}
    rows = []
    for code, vals in scored.items():
        contributions, total = {}, 0.0
        for k, wk in w.items():
            norm = 0.5 if hi[k] == lo[k] else (vals[k] - lo[k]) / (hi[k] - lo[k])
            if wk < 0:
                norm = 1 - norm
            points = 100 * abs(wk) * norm
            total += points
            contributions[k] = {
                "value": vals[k], "norm": round(norm, 4), "weight": round(wk, 4), "points": round(points, 2),
            }
        rows.append({"code": code, "score": round(total, 1), "contributions": contributions})
    # Ties: higher scale first, then code, so the order is stable.
    rows.sort(key=lambda r: (-r["score"], -float(kpis[r["code"]].get("scale") or 0), r["code"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {
        "objective": objective,
        "weights_used": {k: round(v, 4) for k, v in w.items()},
        "method": "each KPI min-max normalised across these candidates (negative weight = lower is "
        "better), score = 100 * sum(|weight| * norm); relative to this set only",
        "ranking": rows,
        "not_scored": not_scored,
    }
