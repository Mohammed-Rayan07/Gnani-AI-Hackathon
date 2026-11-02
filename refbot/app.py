"""Dhan Seva as a service, implementing both harness contracts.

    uvicorn refbot.app:app --port 8100
    # audio: http://localhost:8100/v1/call/start   (version via ?v=v1|v2)
    # text:  http://localhost:8100/v2/text/start
"""

from __future__ import annotations

import base64
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from chakravyuh import audio
from chakravyuh.clients import build_clients
from chakravyuh.config import get_settings

from .brain import Session
from .pipeline import RefBotVoice

app = FastAPI(title="Dhan Seva reference bot (fictional bank)")
_settings = get_settings()
_clients = build_clients(_settings)
BOTS = {v: RefBotVoice(v, _clients.stt, _clients.tts, _clients.bot_llm) for v in ("v1", "v2")}


def _bot(version: str) -> RefBotVoice:
    if version not in BOTS:
        raise HTTPException(404, "version must be v1 or v2")
    return BOTS[version]


def _b64(s: str | None) -> str:
    return base64.b64encode((s or "").encode("utf-8")).decode("ascii")


def _wav_response(r, sid: str | None = None) -> Response:
    headers = {"X-Bot-Text": _b64(r.text), "X-End-Call": "1" if r.end_call else "0"}
    if r.heard_caller is not None:
        headers["X-Bot-Heard"] = _b64(r.heard_caller)
    if sid:
        headers["X-Session-Id"] = sid
    return Response(audio.wav_bytes(r.audio, r.sr), media_type="audio/wav", headers=headers)


@app.post("/{version}/call/start")
async def call_start(version: str):
    sid, r = await _bot(version).start()
    return _wav_response(r, sid)


@app.post("/{version}/call/{sid}/turn")
async def call_turn(version: str, sid: str, audio_file: UploadFile = File(..., alias="audio")):
    bot = _bot(version)
    if sid not in bot.sessions:
        raise HTTPException(404, "unknown session")
    x, sr = audio.read_wav_bytes(await audio_file.read())
    return _wav_response(await bot.turn(sid, x, sr))


@app.post("/{version}/call/{sid}/end")
async def call_end(version: str, sid: str):
    _bot(version).end(sid)
    return {"ok": True}


class TextIn(BaseModel):
    text: str


@app.post("/{version}/text/start")
async def text_start(version: str):
    bot = _bot(version)
    sid = uuid.uuid4().hex[:12]
    bot.sessions[sid] = Session(sid, version)       # text mode: no greeting audio, no TTS credits
    return {"session_id": sid, "text": bot.brain.greeting()}


@app.post("/{version}/text/{sid}/turn")
async def text_turn(version: str, sid: str, body: TextIn):
    bot = _bot(version)
    if sid not in bot.sessions:
        raise HTTPException(404, "unknown session")
    t = await bot.text_turn(sid, body.text)
    return {"text": t.reply, "end_call": t.end_call, "action": t.action}


@app.get("/health")
async def health():
    return {"ok": True, "mode": _settings.mode_label, "bot_llm": _clients.bot_llm.label}
