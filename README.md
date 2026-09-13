# airport-agent-lite

A chat agent that helps analysts screen US airports for added flight and passenger capacity.
It pulls public aviation data live, computes a deterministic screening score, and narrates it.

Minimal by design: one LLM at a time, two keyless live APIs, one scoring function, one JSON
history file, one HTML page. About 600 lines of Python and JavaScript.

## Run

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then put your key in LLM_API_KEY
.\.venv\Scripts\python -m uvicorn app:app --port 8010
```

Open http://127.0.0.1:8010 in Chrome (the mic button uses Chrome's built-in speech recognition).

## Configuration (`.env`)

| Variable | Meaning |
|----------|---------|
| `LLM_BASE_URL` | Any OpenAI-compatible endpoint. Default Groq, `https://api.groq.com/openai/v1`. Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `LLM_API_KEY` | The key for that endpoint |
| `LLM_MODEL` | Default `openai/gpt-oss-120b` on Groq; `gemini-3.5-flash-lite` on Gemini |

One provider runs at a time. There is no fallback and no retry: a 429 or 5xx shows in the chat
bubble as-is, and the failed turn is not saved. Switch provider by editing `.env` and restarting.

## Try these

- Which New England airports are the best candidates for terminal expansion?
- And why? / Only Massachusetts. / What if delays matter more?
- Is LAX or SNA more congested?
- What is the long-haul share at ANC?
- Is there unmet demand at SFO, and why?

Every reply uses the same order: Answer, Airports considered, Ranking, Reasoning, Assumptions and
limits, Sources. Under it, a collapsed "tools" block shows each tool call, its arguments, and the
raw result, so the numbers in the answer can be checked against the data.

## Layout

| File | Role |
|------|------|
| `app.py` | FastAPI routes, the agent loop (up to 5 tool rounds), `history.json` read/write |
| `tools.py` | Live fetchers: BTS T-100 (Socrata) aggregated into KPIs, FAA NAS status parsed into delay severity |
| `calc.py` | `score_airports`: min-max normalise, weight, rank. Presets for expansion, congestion, unmet demand |
| `prompts.py` | System prompt and the three tool schemas |
| `static/index.html` | The whole UI: chat, tool traces, session sidebar, starter questions, mic |
| `tests/` | Pytest for the pure functions (scoring and KPI aggregation) |
| `history.json` | All sessions, `{session_id: [OpenAI-format messages]}`, rewritten after each turn (git-ignored) |

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
```

Tests never touch the network. The live APIs and the LLM are checked by hand in the browser.

See `DESIGN.md` for the scoring method, data sources, and limitations.
