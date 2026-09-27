#!/usr/bin/env python3
"""
docs/fastapi_adapter.py — OPTIONAL. Not used by default.

bot.py ships as a zero-dependency stdlib `http.server` app on purpose (see
README.md "Why no FastAPI"). But composer.py / reply_engine.py / state_store.py
have no framework coupling at all, so if your team would rather run this on
FastAPI + uvicorn (e.g. because your deploy target/CI already assumes it,
or you want automatic OpenAPI docs), this is the entire adapter — same
logic, different transport. It is a straight port of bot.py's route bodies.

Install:   pip install fastapi "uvicorn[standard]"
Run:       uvicorn docs.fastapi_adapter:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Optional

import bot as core  # reuse every stateful store + handler function from bot.py

app = FastAPI(title="Vera Bot (FastAPI adapter)")


@app.get("/v1/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(__import__("time").time() - core.START_TIME),
        "contexts_loaded": core.contexts.counts(),
    }


@app.get("/v1/metadata")
async def metadata():
    return core.TEAM_METADATA


class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str


@app.post("/v1/context")
async def push_context(body: CtxBody):
    status, resp = core.handle_context(body.model_dump())
    return resp  # FastAPI 200s by default; swap to JSONResponse(resp, status) if you need the 400/409 codes


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


@app.post("/v1/tick")
async def tick(body: TickBody):
    return core.handle_tick(body.model_dump())


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    return core.handle_reply(body.model_dump())


@app.post("/v1/teardown")
async def teardown():
    core.contexts.clear()
    core.conversations.clear()
    core.sent_suppression_keys.clear()
    return {"status": "wiped"}
