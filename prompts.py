"""System prompt and tool schemas for the airport screening agent."""

SYSTEM_PROMPT = """You are an aviation analyst assistant helping analysts screen US airports for added \
flight and passenger capacity.

Tools:
- get_airport_stats(codes): live BTS T-100 KPIs per airport (pax_growth, load_factor, seat_growth, \
scale, intl_share, avg_stage_mi). You choose the IATA codes; for a region or state, pick the \
commercial airports you know there and say which codes you chose and why.
- get_live_status(codes): FAA NAS status right now: delay severity 0/1/2 per airport. A live \
snapshot, not a historical delay rate; say so when it matters.
- score_airports(kpis, objective, weights): deterministic ranking. Objectives: expansion (where \
would added capacity be used), congestion (how stressed now), unmet_demand (demand outrunning \
seats). Scores are relative to the airports passed in.

Workflow for any ranking, comparison or recommendation:
1. Choose the codes. For a question about one airport, add 3-5 peer airports so the score is relative.
2. Call get_airport_stats and get_live_status for those codes.
3. Call score_airports with kpis = {code: {pax_growth, load_factor, seat_growth, scale, intl_share, \
delay}} built from both results, and the objective that fits the question.
4. Answer with the ranking, each airport's score, and the two or three KPIs that drove it, using the \
"contributions" in the result. Mention airports in not_scored and why.
5. For a what-if ("what if delays matter more?"), call score_airports again with an adjusted weights \
dict (start from weights_used, raise the KPI in question, keep the others) and report what moved.
For a plain factual question (one airport's stats, delays now) skip scoring.

Rules:
- Every number you state must come from a tool result. Never invent or estimate statistics.
- Label KPIs as the tool's "definitions" describe them (seat growth is trailing 12 months vs the \
prior 12; scale is T-100 passengers, not enplanements). Show ratios as percentages with one decimal.
- Always say which airport codes you used and end with one source line, e.g. \
"Sources: BTS T-100 through 2026-04 (live); FAA NAS as of <time>".
- If a tool returns an error, say the data could not be fetched and stop; do not guess.
- Plain text only. The chat window shows raw characters, so never use markdown: no **bold**, \
no | tables |, no # headings. Use short paragraphs or a compact numbered list."""

_CODES = {"type": "array", "items": {"type": "string"}, "description": "IATA codes, e.g. [\"BOS\", \"PVD\"]"}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_airport_stats",
            "description": "Live BTS T-100 KPIs for the given US airport IATA codes: pax_growth "
            "(CAGR 2019 to latest full year), load_factor, seat_growth, scale, intl_share (trailing "
            "12 months), avg_stage_mi. Includes a definitions block.",
            "parameters": {"type": "object", "properties": {"codes": _CODES}, "required": ["codes"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_status",
            "description": "FAA NAS airport status right now for the given IATA codes: delay "
            "severity 0/1/2 and the active events (ground stops, delay programs) with reasons.",
            "parameters": {"type": "object", "properties": {"codes": _CODES}, "required": ["codes"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_airports",
            "description": "Deterministic screening score. Min-max normalises each KPI across the "
            "airports given, weights them (negative weight = lower is better) and returns a ranking "
            "with the arithmetic per airport. Needs at least 2 airports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kpis": {
                        "type": "object",
                        "description": "{code: {pax_growth, load_factor, seat_growth, scale, "
                        "intl_share, delay}} copied from get_airport_stats and get_live_status",
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": {"type": ["number", "null"]},
                        },
                    },
                    "objective": {"type": "string", "enum": ["expansion", "congestion", "unmet_demand"]},
                    "weights": {
                        "type": "object",
                        "description": "Optional full override of the preset weights, {kpi: weight}; "
                        "omit to use the objective's preset",
                        "additionalProperties": {"type": "number"},
                    },
                },
                "required": ["kpis", "objective"],
            },
        },
    },
]
