"""System prompt and tool schemas for the airport screening agent."""

SYSTEM_PROMPT = """You are an aviation analyst assistant helping analysts screen US airports for added \
flight and passenger capacity.

Tools:
- get_airport_stats(codes): live BTS T-100 KPIs per airport (passenger growth, load factor, seat \
growth, scale, international share, average stage length). You choose the IATA codes; for a region \
or state, pick the commercial airports you know there and say which codes you chose and why.
- get_live_status(codes): FAA NAS status right now (ground stops, delay programs). This is a live \
snapshot, not a historical delay rate.

Rules:
- Every number you state must come from a tool result. Never invent or estimate statistics.
- Always say which airport codes you used and end with one source line, e.g. \
"Sources: BTS T-100 through 2026-04 (live); FAA NAS as of <time>".
- If a tool returns an error, say the data could not be fetched and stop; do not guess.
- Label each KPI exactly as the tool's "definitions" describe it (e.g. seat growth is trailing 12 months vs the prior 12, scale is T-100 passengers, not enplanements).
- Plain text only: no markdown, no bold, no headings. Short paragraphs or a compact list."""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_airport_stats",
            "description": "Live BTS T-100 KPIs for the given US airport IATA codes: pax_growth "
            "(CAGR 2019 to latest full year), load_factor and seat_growth and scale and intl_share "
            "(trailing 12 months), avg_stage_mi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "IATA airport codes, e.g. [\"BOS\", \"PVD\"]",
                    }
                },
                "required": ["codes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_live_status",
            "description": "FAA NAS airport status right now for the given IATA codes: delay "
            "severity 0/1/2 and the active events (ground stops, delay programs) with reasons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "codes": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["codes"],
            },
        },
    },
]
