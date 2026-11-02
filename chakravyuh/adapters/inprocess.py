from __future__ import annotations

import numpy as np

from refbot.pipeline import RefBotVoice

from . import BotReply


class InProcessRefBot:
    """Dhan Seva called directly. Latency = its real processing time (its own Prisma + LLM + Timbre calls)."""

    name = "inprocess"
    capabilities = {"audio_io", "exposes_reply_text"}

    def __init__(self, version: str, stt, tts, llm):
        self.version = version
        self.bot = RefBotVoice(version, stt, tts, llm)

    @property
    def label(self) -> str:
        return self.bot.label

    async def start_call(self) -> tuple[str, BotReply]:
        sid, r = await self.bot.start()
        return sid, BotReply(r.audio, r.sr, text_true=r.text, response_latency_s=r.processing_s, total_s=r.processing_s)

    async def turn(self, session_id: str, audio: np.ndarray, sr: int, *, reference_text: str | None = None) -> BotReply:
        r = await self.bot.turn(session_id, audio, sr, reference_text=reference_text)
        return BotReply(r.audio, r.sr, text_true=r.text, heard_caller=r.heard_caller, end_call=r.end_call,
                        response_latency_s=r.processing_s, total_s=r.processing_s, extra={"action": r.action})

    async def end_call(self, session_id: str) -> None:
        self.bot.end(session_id)
