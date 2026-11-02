"""Gnani Prisma speech-to-text (REST, POST /stt/v3).

Request shape follows Gnani's official LiveKit plugin: multipart `audio_file`,
`language_code`, `format`, plus `model` for Prisma v3.0. Clips must be <= 30 s,
so long replies are split at silences first.

The harness deliberately uses REST, not the streaming WebSocket: WS must be fed
at real-time cadence with per-org session caps, so a 72-call regression could
not run in parallel, be cached, or replay deterministically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
import numpy as np

from .. import audio, vad
from ..cache import DiskCache, key
from ..config import Settings
from ..ledger import Ledger
from ._http import GnaniAPIError, request_with_retry

log = logging.getLogger("chakravyuh.prisma")


@dataclass
class STTResult:
    text: str
    detected_language: str | None = None
    raw: list[dict] = field(default_factory=list)
    cached: bool = False


def _detected_lang(resp: dict) -> str | None:
    for k in ("detected_language_code", "detected_language", "language_code", "language"):
        v = resp.get(k)
        if isinstance(v, str) and v:
            return v
    return None


class PrismaClient:
    def __init__(self, s: Settings, ledger: Ledger, cache: DiskCache):
        self.s = s
        self.ledger = ledger
        self.cache = cache
        self.upload_sr = s.stt_upload_sr
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0))

    @property
    def label(self) -> str:
        return f"{self.s.stt_model} ({self.s.stt_language}, {self.s.stt_format})"

    async def _post(self, wav: bytes, language: str) -> dict:
        data = {"language_code": language, "format": self.s.stt_format}
        if self.s.stt_model:
            data["model"] = self.s.stt_model
        r = await request_with_retry(
            self._http, "POST", f"{self.s.gnani_base_url}/stt/v3",
            what="Prisma STT",
            headers={"X-API-Key-ID": self.s.gnani_api_key},
            data=data,
            files={"audio_file": ("audio.wav", wav, "audio/wav")},
        )
        return r.json()

    async def _transcribe_chunk(self, x: np.ndarray, sr: int, language: str) -> tuple[dict, bool]:
        x_up = audio.resample(x, sr, self.upload_sr)
        wav = audio.wav_bytes(x_up, self.upload_sr)
        k = key("prisma", wav, self.s.stt_model, language, self.s.stt_format)
        hit = self.cache.get_json(k)
        if hit is not None:
            return hit, True
        seconds = len(x) / sr
        with self.ledger.reserve("stt", seconds, self.ledger.rates.stt(seconds), meta=f"{seconds:.1f}s {language}"):
            try:
                resp = await self._post(wav, language)
            except GnaniAPIError as e:
                # Fallback from the plan's risk table: if 8 kHz is rejected, upsample the
                # degraded line audio to 16 kHz (the band-limit artefacts survive).
                if self.upload_sr == 8000 and e.status in (400, 415, 422):
                    log.warning("Prisma rejected 8 kHz upload (%s); switching to 16 kHz uploads", e.status)
                    self.upload_sr = 16000
                    wav = audio.wav_bytes(audio.resample(x, sr, 16000), 16000)
                    resp = await self._post(wav, language)
                else:
                    raise
        self.cache.put_json(k, resp)
        return resp, False

    async def transcribe(self, x: np.ndarray, sr: int, *, language: str | None = None, reference_text: str | None = None) -> STTResult:
        """`reference_text` is ignored by the live client (it only drives the offline fake)."""
        language = language or self.s.stt_language
        texts, raws, langs, all_cached = [], [], [], True
        for chunk in vad.split_for_stt(x, sr):
            resp, cached = await self._transcribe_chunk(chunk, sr, language)
            all_cached &= cached
            raws.append(resp)
            texts.append((resp.get("transcript") or "").strip())
            langs.append(_detected_lang(resp))
        lang = next((l for l in langs if l), None)
        return STTResult(" ".join(t for t in texts if t), lang, raws, all_cached)

    async def aclose(self) -> None:
        await self._http.aclose()
