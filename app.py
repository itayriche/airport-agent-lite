"""Minimal airport screening agent: FastAPI + Groq. Step 1: plain chat, no tools."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from openai import APIError, APIStatusError, OpenAI
from pydantic import BaseModel

from prompts import SYSTEM_PROMPT

load_dotenv()

MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])

app = FastAPI(title="airport-agent-lite")


class ChatIn(BaseModel):
    session_id: str
    message: str


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/chat")
def chat(body: ChatIn):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body.message},
    ]
    try:
        resp = client.chat.completions.create(model=MODEL, messages=messages)
    except APIStatusError as e:
        detail = e.body.get("message") if isinstance(e.body, dict) else None
        return {"reply": f"Groq error {e.status_code}: {detail or e.message}", "error": True}
    except APIError as e:
        return {"reply": f"Groq error: {e}", "error": True}
    return {"reply": resp.choices[0].message.content or ""}
