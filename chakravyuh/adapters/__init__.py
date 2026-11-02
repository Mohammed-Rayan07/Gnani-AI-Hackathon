"""Bot adapters: how the harness talks to the bot under test.

audio-http  black box: 8 kHz wav in, wav out (optionally exposes reply text)
text-http   text-only bots; the harness wraps them with Prisma + Timbre, so the
            scorecard is stamped "logic-only" (the bot's own voice stack is untested)
inprocess   the reference bot Dhan Seva, called directly (same code as its HTTP app)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class BotReply:
    audio: np.ndarray | None
    sr: int
    text_true: str | None = None        # the bot's real reply text, if it exposes it
    heard_caller: str | None = None     # what the bot's STT heard, if it exposes it
    end_call: bool = False
    response_latency_s: float | None = None
    total_s: float | None = None
    extra: dict = field(default_factory=dict)


class BotAdapter(Protocol):
    name: str
    label: str
    version: str
    capabilities: set[str]               # audio_io, text_io, streaming, exposes_reply_text

    async def start_call(self) -> tuple[str, BotReply]: ...
    async def turn(self, session_id: str, audio: np.ndarray, sr: int, *, reference_text: str | None = None) -> BotReply: ...
    async def end_call(self, session_id: str) -> None: ...
