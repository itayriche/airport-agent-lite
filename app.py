"""Minimal airport screening agent: FastAPI + Groq. Step 2: chat with a JSON history file."""

import json
import os
import threading

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from openai import APIError, APIStatusError, OpenAI
from pydantic import BaseModel

from prompts import SYSTEM_PROMPT

load_dotenv()

MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
HISTORY_FILE = "history.json"
CONTEXT_MESSAGES = 30  # most recent messages sent to the model, cut at a turn boundary

client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])
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
        messages.append({"role": "user", "content": body.message})
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, *recent(messages)],
            )
        except APIStatusError as e:
            detail = e.body.get("message") if isinstance(e.body, dict) else None
            return {"reply": f"Groq error {e.status_code}: {detail or e.message}", "error": True}
        except APIError as e:
            return {"reply": f"Groq error: {e}", "error": True}
        reply = resp.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": reply})
        save_history(history)
    return {"reply": reply}
