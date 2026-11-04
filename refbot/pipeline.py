"""Dhan Seva's own voice stack: Prisma hears the caller, the brain replies, Timbre speaks.
Used in-process by the harness and behind the FastAPI app."""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass

import numpy as np

from chakravyuh import voices

from .brain import BotTurn, RefBotBrain, Session


def reply_language(text: str, version: str) -> str:
    if version == "v1":
        return "en-IN"
    for lang, pat in (("hi-IN", r"[ऀ-ॿ]"), ("ta-IN", r"[஀-௿]"), ("kn-IN", r"[ಀ-೿]"),
                      ("bn-IN", r"[ঀ-৿]"), ("te-IN", r"[ఀ-౿]")):
        if re.search(pat, text):
            return lang
    return "en-IN"


@dataclass
class VoiceReply:
    audio: np.ndarray
    sr: int
    text: str
    heard_caller: str | None
    end_call: bool
    action: str | None
    processing_s: float


class RefBotVoice:
    def __init__(self, version: str, stt, tts, llm, voice: str | None = None):
        self.brain = RefBotBrain(version, llm)
        self.stt, self.tts = stt, tts
        self.voice = voice or os.environ.get("REFBOT_VOICE", "").strip() or None   # None = per-language voice
        self.sessions: dict[str, Session] = {}

    @property
    def label(self) -> str:
        return self.brain.label

    async def _speak(self, text: str) -> tuple[np.ndarray, int]:
        lang = reply_language(text, self.brain.version)
        return await self.tts.synthesize(text, voice=self.voice or voices.refbot_voice(lang), language=lang)

    async def start(self) -> tuple[str, VoiceReply]:
        sid = uuid.uuid4().hex[:12]
        self.sessions[sid] = Session(sid, self.brain.version)
        t0 = time.perf_counter()
        text = self.brain.greeting()
        x, sr = await self._speak(text)
        return sid, VoiceReply(x, sr, text, None, False, None, time.perf_counter() - t0)

    async def turn(self, sid: str, caller_audio: np.ndarray, sr: int, *, reference_text: str | None = None) -> VoiceReply:
        t0 = time.perf_counter()
        heard = await self.stt.transcribe(caller_audio, sr, reference_text=reference_text)
        bt: BotTurn = await self.brain.respond(self.sessions[sid], heard.text)
        x, out_sr = await self._speak(bt.reply or "...")
        return VoiceReply(x, out_sr, bt.reply, heard.text, bt.end_call, bt.action, time.perf_counter() - t0)

    async def text_turn(self, sid: str, caller_text: str) -> BotTurn:
        return await self.brain.respond(self.sessions[sid], caller_text)

    def end(self, sid: str) -> None:
        self.sessions.pop(sid, None)
