# Design

## What the agent does

An analyst asks a question in plain language. The model chooses which airports are relevant,
fetches their data live, asks a deterministic scoring function to rank them, and explains the
ranking. The model never computes a statistic itself: every number in an answer comes from a tool
result, and the tool calls are shown under the reply.

```
browser ──POST /chat──> app.py ──> LLM (OpenAI-compatible, tool calling)
                          │            │ asks for tools, up to 5 rounds
                          │            v
                          ├── get_airport_stats ──> tools.fetch_t100 ──> BTS T-100 (Socrata, live)
                          ├── get_live_status  ──> tools.fetch_nas  ──> FAA NAS status XML (live)
                          └── score_airports   ──> calc.score_airports (pure Python)
                          history.json  {session_id: [messages incl. tool calls and results]}
```

## Data

Two keyless public feeds, called fresh on every question. No cache, no bundled snapshots.

**BTS T-100 by origin airport** (`data.bts.gov/resource/r495-tyji.json`). T-100 is the form on
which every US airline reports its monthly flights, seats and passengers to the Bureau of
Transportation Statistics; this dataset sums it per origin airport. One row per airport per
month, 2019 to the latest published month (2026-04 at the time of writing), all commercial
service including cargo carriers. Fields used: departures, passengers, seats, international
departures, average flight distance. Aggregated per airport into:

| KPI | Definition |
|-----|------------|
| `pax_growth` | CAGR of total passengers, calendar 2019 to the latest full calendar year |
| `load_factor` | passengers / seats over the trailing 12 months |
| `seat_growth` | seats in the trailing 12 months vs the 12 months before |
| `scale` | passengers in the trailing 12 months (T-100 departing passengers, not FAA enplanements) |
| `intl_share` | international departures / all departures, trailing 12 months |
| `avg_stage_mi` | mean monthly average flight distance, statute miles (context for long-haul questions) |
| `intl_pax_share` | international passengers / all passengers, trailing 12 months. Not scored. A large gap below `intl_share` means the international flights are freighters (ANC: about 15% of departures, under 1% of passengers) |
| `freight_lbs` | freight + mail pounds departed, trailing 12 months. Not scored; lets the model recognise a cargo hub |

**FAA NAS airport status** (`nasstatus.faa.gov/api/airport-status-information`). The Federal
Aviation Administration's National Airspace System feed of what is active right now: ground
stops (flights bound for the airport are held at their origin), ground delay programs (flights
are metered with assigned delays), general delay notices, and closure NOTAMs (Notices to Air
Missions about a facility condition), with reasons. Mapped to `delay`: 0 nothing active, 1 any
active program or notice, 2 ground stop. Closure NOTAMs are usually about general aviation
(private, non-airline flying), so they are not treated as severity 2; the reason text is passed
to the model.

Geography is the model's job. The tools take explicit IATA codes; the prompt tells the model to
name the codes it chose so a wrong choice is visible.

## Scoring (`calc.py`)

`score_airports(kpis, objective, weights=None)`

1. Weights come from a preset for the objective, or from a dict the model passes for a what-if.
   They are normalised so absolute values sum to 1.
2. An airport missing any weighted KPI is listed in `not_scored` with the reason.
3. Each weighted KPI is min-max normalised across the airports in the call: `(v - min) / (max - min)`.
   A negative weight flips it (lower is better). All-equal values give 0.5.
4. `score = 100 × Σ(|w| × norm)`. Per-KPI points are returned in `contributions`.
5. Ranked by score; ties broken by scale, then code.

Presets:

| Objective | Weights |
|-----------|---------|
| `expansion` | pax_growth .30, load_factor .20, seat_growth .20, scale .15, delay .15 |
| `congestion` | load_factor .40, delay .40, scale .20 |
| `unmet_demand` | load_factor .35, delay .25, pax_growth .25, seat_growth −.15 (seats not keeping up) |

Scores are relative to the candidate set, not to all US airports. The prompt therefore tells the
model to add three to five peers when asked about one airport, and two airports always score 100
and 0. This is a screening rank for further assessment, not a forecast, and not a dollar model.

## Answer format

The system prompt fixes the order of every reply so an analyst can find the same thing in the
same place each time:

1. **Answer**: the direct answer in one or two sentences.
2. **Airports considered**: the codes used and why they were chosen (the scoping decision).
3. **Ranking**: one line per airport with score, the KPIs that drove it and their points from
   `contributions`, and what held it back. Omitted for plain factual questions.
4. **Reasoning**: objective, weights used, what the score means (relative to this set), why the
   top airport beat the next one.
5. **Analyst view**: the model's own judgment, marked as opinion and kept apart from the score:
   what the ranking misses (a cargo hub whose international share is freighters, growth from a
   tiny base, an airport held back only by the delay snapshot), what may not hold, what to check
   next. It may disagree with the ranking but must say why, using only numbers from the tools.
6. **Assumptions and limits**: screening rank not a profit forecast, live delay snapshot, cargo in
   T-100, no gate/runway/slot data, scope chosen by the model, anything missing.
7. **Sources**: data vintage and the FAA timestamp.

Follow-ups keep the format: "why" answers from the stored contributions without new tool calls,
a re-scope re-runs the workflow with new codes, a what-if re-scores and shows before and after.

## Key tradeoffs

The brief says to prioritise clarity and reasoning over completeness. Every choice below picks
the option with the fewest moving parts that still meets the requirement, so that a reviewer can
read the whole system in one sitting.

**Stack**

| Decision | Chosen | Alternative | Why, and what it costs |
|----------|--------|-------------|------------------------|
| Agent framework | `openai` SDK, native tool calling, a 25-line loop | LangChain / LangGraph | The loop is the whole agent: call model, run tools, repeat. A framework would hide it behind abstractions and add a dependency tree larger than this project. Cost: no built-in tracing, memory classes or graph visualisation; the trace is our own `tools` block. |
| Chat UI | One `index.html`, vanilla JS, served by FastAPI | Streamlit / Gradio | The page is served from disk with no build step and no reruns, owns the mic (Web Speech API needs the browser), and can render the tool trace and session sidebar exactly as wanted. Cost: hand-written CSS and JS instead of widgets. |
| Web server | FastAPI + uvicorn, sync handlers | Flask; or Streamlit's own server | Pydantic validation of the request body and a JSON API the page and the tests can call. Cost: one more dependency than Flask; async is unused. |
| LLM provider | One OpenAI-compatible endpoint chosen by env (Groq gpt-oss-120b; Gemini flash-lite as the spare) | Several providers with fallback; OpenRouter | One client, one code path; switching is an `.env` edit. Cost: a quota outage stops the demo until the block is swapped and the server restarted. Gemini's thought-signature quirk is the one provider-specific line. |
| Voice | Chrome's built-in speech recognition (Web Speech API) | Whisper via Groq or OpenAI | No audio upload, no key, no extra endpoint. Cost: Chrome and Edge only; no transcription in Firefox or Safari. |
| History | `history.json`, whole file rewritten atomically | SQLite; a per-session file; a database | Readable and diffable with any editor; one function to load, one to save. Cost: does not scale past a few hundred sessions and is single-process only. |
| Data handling | Plain Python loops over Socrata rows | pandas | Six KPIs over a few hundred rows per airport do not need a dataframe. Cost: the aggregation is more lines than a `groupby`. |
| Tests | pytest on the pure functions (scoring, KPI aggregation, XML parsing) | End-to-end tests with a mocked LLM and mocked APIs | The deterministic core is what the brief asks to be checkable; the LLM and live feeds are verified by hand in the browser. Cost: a route or prompt regression is not caught automatically. |

**Data and scoring**

| Decision | Chosen | Alternative | Why, and what it costs |
|----------|--------|-------------|------------------------|
| Data sources | Two keyless live feeds: BTS T-100 (airline-reported monthly traffic per airport) and FAA NAS (live delay programs) | FAA ASPM/OPSNET on-time data, OpenSky or aviationstack flight data, airport master files | Both are free, need no key, cover every US commercial airport and answer the four sample questions. Cost: no physical capacity (gates, runways, slots), no historical delay rate, no route-level long-haul data. |
| Freshness | Live on every question, no cache | Cached responses or bundled snapshots | Nothing to invalidate or explain; the source line shows the vintage. Cost: every question waits on BTS and FAA; a feed outage is an error, not a degraded answer. |
| Geography | The model picks the IATA codes | A state/region table | No table to maintain; works for any geography the model knows. Cost: a wrong or missing airport is caught only because the reply lists the codes. |
| Score | Min-max within the candidate set, weighted sum | Scoring against fixed national thresholds; a regression model | Simple, explainable arithmetic shown per airport; what-ifs are one re-call with new weights. Cost: scores are not comparable across questions, and two airports always give 100 and 0. |
| Delay signal | Live FAA severity 0/1/2 | Historical on-time performance | A real "right now" congestion signal with reasons. Cost: not a rate; the same question can score differently an hour later. |
| Answer shape | Fixed seven-section template in the prompt, with one section reserved for the model's own judgment | Free-form narration | Same order every time; reasoning, opinion and limits are always present and kept apart from the arithmetic. Cost: longer replies and more tokens per turn on the free tier. |

## Agent loop and memory

- One provider at a time via `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`; native tool calling
  through the `openai` SDK; no streaming, no retries, no fallback. Errors show in the chat.
- Up to 5 tool rounds per user message; a typical ranking takes 3 (stats, status, score).
- `history.json` holds every session as OpenAI-format messages, including tool calls and tool
  results, rewritten atomically after each turn. The page rebuilds the tool trace from it on reload.
- Each call sends the system prompt plus the last 30 messages, advanced to a user message so a
  tool call is never separated from its result.
- Gemini's OpenAI-compatible endpoint requires a thought signature on replayed tool calls; the app
  adds Google's documented dummy value when the host is Google and strips it otherwise, so a
  session can move between providers.


## Limitations

- **Delays are live, not historical.** `delay` is the FAA feed right now. "What if delays matter
  more" reweights a snapshot; there is no on-time-performance rate in this build.
- **No physical capacity data.** Runways, gates, slots, terminal size are not in either feed.
- **No route detail.** Long-haul is approximated by international share and average stage length,
  and T-100 includes cargo flights, which inflates international share at cargo hubs such as ANC.
- **Scale is not enplanements.** T-100 departing passengers, all carriers.
- **Region resolution is the model's knowledge.** No state table; the reply lists the codes used.
- **Publication lag.** BTS data ends a few months before today.
- **Free-tier quotas.** Groq's daily token limit can run out during a demo; the error is shown,
  not retried.
