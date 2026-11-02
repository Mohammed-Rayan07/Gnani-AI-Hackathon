"""Clients for Gnani Prisma (STT), Timbre (TTS + voice cloning) and OpenAI-compatible LLMs.

`build_clients(settings)` returns live clients, or offline fakes when
CHAKRAVYUH_OFFLINE=1 (dry runs and tests only; every report is stamped).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..cache import DiskCache
from ..config import Settings
from ..ledger import Ledger, Rates


@dataclass
class Clients:
    stt: Any
    tts: Any
    persona_llm: Any
    bot_llm: Any
    judge_llm: Any
    ledger: Ledger
    settings: Settings


def build_ledger(s: Settings) -> Ledger:
    return Ledger(
        s.cache_dir / "ledger.sqlite",
        s.credit_cap,
        Rates(s.rate_stt_per_min, s.rate_tts_per_1k_chars, s.rate_vc_per_call),
    )


def build_clients(s: Settings) -> Clients:
    ledger = build_ledger(s)
    if s.offline:
        from .offline import OfflineLLM, OfflineSTT, OfflineTTS

        return Clients(OfflineSTT(), OfflineTTS(), OfflineLLM("persona"), OfflineLLM("bot"), OfflineLLM("judge"), ledger, s)

    from .llm import LLMClient
    from .prisma import PrismaClient
    from .timbre import TimbreClient

    if not s.gnani_api_key:
        raise SystemExit("GNANI_API_KEY is not set. Copy .env.example to .env and fill it in (or set CHAKRAVYUH_OFFLINE=1 for a dry run).")
    stt = PrismaClient(s, ledger, DiskCache(s.cache_dir, "stt"))
    tts = TimbreClient(s, ledger, DiskCache(s.cache_dir, "tts"))
    return Clients(
        stt, tts,
        LLMClient(s.persona_llm, DiskCache(s.cache_dir, "llm")),
        LLMClient(s.bot_llm, DiskCache(s.cache_dir, "llm")),
        LLMClient(s.judge_llm, DiskCache(s.cache_dir, "llm")),
        ledger, s,
    )
