"""Minimal airport screening agent: FastAPI + Groq + two live data tools + a scoring tool + JSON history."""

import json
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from openai import APIError, APIStatusError, OpenAI
from pydantic import BaseModel

import calc
import tools
from prompts import SYSTEM_PROMPT, TOOL_SCHEMAS

load_dotenv()

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
GOOGLE = "googleapis.com" in BASE_URL
# Gemini's OpenAI-compatible endpoint rejects a replayed tool call without a thought signature;
# Google documents this dummy value. Other hosts do not know the field, so it is stripped for them.
DUMMY_SIGNATURE = {"google": {"thought_signature": "skip_thought_signature_validator"}}
HISTORY_FILE = "history.json"
CONTEXT_MESSAGES = 30  # most recent messages sent to the model, cut at a turn boundary
MAX_ROUNDS = 5  # tool-call rounds per user message

TOOLS = {
    "get_airport_stats": lambda args: tools.fetch_t100(args.get("codes", [])),
    "get_live_status": lambda args: tools.fetch_nas(args.get("codes", [])),
    "score_airports": lambda args: calc.score_airports(
        args.get("kpis", {}), args.get("objective", "expansion"), args.get("weights")),
}

client = OpenAI(base_url=BASE_URL, api_key=os.environ["LLM_API_KEY"],
                max_retries=0)  # no retries: a 429/5xx is shown in the chat as-is
app = FastAPI(title="airport-agent-lite")
_lock = threading.Lock()  # one process, but FastAPI runs sync handlers in a thread pool


# ---- history.json: {session_id: [OpenAI-format messages]} ---------------------------------

def load_history() -> dict:
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_history(history: dict) -> None:
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    os.replace(tmp, HISTORY_FILE)


def recent(messages: list, n: int = CONTEXT_MESSAGES) -> list:
    """Last `n` messages, advanced to the next user message so a turn is never split."""
    start = max(0, len(messages) - n)
    while start < len(messages) and messages[start]["role"] != "user":
        start += 1
    return messages[start:]


# ---- agent loop ----------------------------------------------------------------------------

def run_tool(name: str, arguments: str) -> dict:
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        return {"error": f"bad tool arguments: {e}"}
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(args)
    except Exception as e:  # a tool bug becomes a tool error the model can report, not a 500
        return {"error": f"{name} failed: {type(e).__name__}: {e}"}


def tool_call_dict(tc) -> dict:
    d = {"id": tc.id, "type": "function",
         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
    extra = (tc.model_extra or {}).get("extra_content")  # Gemini's thought signature, if any
    if GOOGLE:
        d["extra_content"] = extra or DUMMY_SIGNATURE
    return d


def for_provider(messages: list) -> list:
    """History may have been written under another provider: add/strip the Google signature."""
    out = []
    for m in messages:
        if m.get("tool_calls"):
            calls = []
            for c in m["tool_calls"]:
                c = dict(c)
                if GOOGLE:
                    c.setdefault("extra_content", DUMMY_SIGNATURE)
                else:
                    c.pop("extra_content", None)
                calls.append(c)
            m = {**m, "tool_calls": calls}
        out.append(m)
    return out


def run_turn(messages: list) -> tuple[str, list]:
    """Append the model's messages (incl. tool calls/results) to `messages`; return (reply, trace)."""
    trace = []
    for _ in range(MAX_ROUNDS):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *for_provider(recent(messages))],
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            reply = msg.content or ""
            messages.append({"role": "assistant", "content": reply})
            return reply, trace
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [tool_call_dict(tc) for tc in msg.tool_calls],
        })
        for tc in msg.tool_calls:
            result = run_tool(tc.function.name, tc.function.arguments)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
            trace.append({"name": tc.function.name, "args": tc.function.arguments, "result": result})
    reply = f"Stopped after {MAX_ROUNDS} tool rounds without a final answer."
    messages.append({"role": "assistant", "content": reply})
    return reply, trace


# ---- routes ------------------------------------------------------------------------------

class ChatIn(BaseModel):
    session_id: str
    message: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/history/{session_id}")
def history(session_id: str):
    with _lock:
        return {"messages": load_history().get(session_id, [])}


@app.post("/chat")
def chat(body: ChatIn):
    with _lock:
        history = load_history()
        messages = history.setdefault(body.session_id, [])
        before = len(messages)
        messages.append({"role": "user", "content": body.message})
        try:
            reply, trace = run_turn(messages)
        except APIStatusError as e:
            del messages[before:]  # a failed turn leaves no trace in the history
            detail = e.body.get("message") if isinstance(e.body, dict) else None
            return {"reply": f"Groq error {e.status_code}: {detail or e.message}", "error": True}
        except APIError as e:
            del messages[before:]
            return {"reply": f"Groq error: {e}", "error": True}
        save_history(history)
    return {"reply": reply, "tools": trace}
