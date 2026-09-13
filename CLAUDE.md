# CLAUDE.md

Minimal rebuild of the airport screening take-home. The design goal is *bare minimum*: before
adding anything, ask whether the brief needs it. `DESIGN.md` explains the scoring and data;
`README.md` explains how to run it.

## Commands

```powershell
.\.venv\Scripts\python -m uvicorn app:app --port 8010     # run (port 8000 is taken on this machine)
.\.venv\Scripts\python -m pytest -q                        # 19 tests, no network
```

Python 3.13 venv (`py -3.13 -m venv .venv`). Detached run on Windows: `Start-Process` with the
venv python, not `&`. Restart the server after editing any `.py` file; `static/index.html` is
served from disk, no restart needed.

## Architecture in five files

- `app.py`: FastAPI. `GET /` (page), `POST /chat`, `GET /history/{id}`, `GET /sessions`. The
  agent loop `run_turn` (max 5 tool rounds), the `TOOLS` name-to-function map, `history.json`
  load/save under a lock, and the Gemini thought-signature add/strip in `for_provider`.
- `tools.py`: `fetch_t100(codes)` (one Socrata call, `t100_kpis` aggregation) and
  `fetch_nas(codes)` (`parse_nas`, `severity`). Tool results carry a `definitions` block so the
  model labels KPIs correctly.
- `calc.py`: `PRESETS` and `score_airports`. The only place a score is computed.
- `prompts.py`: `SYSTEM_PROMPT` (workflow and rules) and `TOOL_SCHEMAS`.
- `static/index.html`: everything in the browser, inline CSS/JS. Sidebar of sessions, starter
  questions on an empty chat, tool trace `<details>` under each reply, mic via
  `webkitSpeechRecognition`.

## Decisions that are deliberate (do not "fix")

- One provider at a time, no fallback, no retries (`max_retries=0`), no streaming. Errors go to
  the chat bubble; a failed turn is not saved.
- No cache of API responses. Every question hits BTS and FAA live.
- The model picks IATA codes; there is no region/state table.
- Scores are min-max within the candidate set. Two airports give 100 and 0 by construction.
- `delay` is live FAA severity, not a historical rate. Closure NOTAMs are severity 1, not 2.
- Plain-text replies; the page renders `textContent`, not markdown. gpt-oss-120b sometimes
  ignores this; Gemini obeys.
- The system prompt fixes a six-section reply order (Answer, Airports considered, Ranking,
  Reasoning, Assumptions and limits, Sources) because the brief asks for clear reasoning and
  explicit assumptions and scoping. Keep the labels if you edit the prompt; DESIGN.md and README
  describe them.
- Tests cover pure functions only. Routes, APIs, and the LLM are checked by hand.

## Gotchas

- Socrata omits fields that are null for a row (domestic-only airports have no
  `outbound_international`). Use `.get`.
- FAA category names: "Ground Stop Programs", "Ground Delay Programs", "Airport Closures".
- Groq free tier: 200k tokens per day for gpt-oss-120b. Tool results are re-sent every round and
  every later turn, so a long session burns quota fast. `.env` keeps both Groq and Gemini
  blocks; only one is uncommented.
- Long bash heredocs with quotes fail in the Windows Git Bash tool. Write files with the Write
  tool or a short Python script.
- Console output with non-ASCII (the model's hyphens) needs `PYTHONIOENCODING=utf-8`.

## Docs to keep in sync

Obsidian vault note "Airport Investment Agent - take-home" (section on the lite rebuild) and
the old repo `airport-investment-agent` (reference only, untouched).
