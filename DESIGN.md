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

**BTS T-100 by origin airport** (`data.bts.gov/resource/r495-tyji.json`). One row per airport
per month, 2019 to the latest published month (2026-04 at the time of writing), all commercial
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

**FAA NAS airport status** (`nasstatus.faa.gov/api/airport-status-information`). What is active
right now: ground stops, ground delay programs, general delay notices, closure NOTAMs, with
reasons. Mapped to `delay`: 0 nothing active, 1 any active program or notice, 2 ground stop.
Closure NOTAMs are usually about general aviation, so they are not treated as severity 2; the
reason text is passed to the model.

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
