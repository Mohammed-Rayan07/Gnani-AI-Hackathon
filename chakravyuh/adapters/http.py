"""HTTP adapters for bots running as services.

audio-http contract (what `refbot/app.py` implements; any bot can implement it):
  POST {base}/call/start                 -> audio/wav body (the greeting)
  POST {base}/call/{sid}/turn  (multipart field "audio", 8 kHz wav) -> audio/wav body
  Response headers: X-Session-Id (start only), X-End-Call: 1|0,
  optional X-Bot-Text / X-Bot-Heard (base64 UTF-8) to enable the harness-noise floor.

text-http contract:
  POST {base}/text/start                 -> {"session_id", "text"}
  POST {base}/text/{sid}/turn  {"text"}  -> {"text", "end_call"}
"""

from __future__ import annotations

import base64
import time

import httpx
import numpy as np

from .. import audio
from . import BotReply


def _b64(h: str | None) -> str | None:
    return base64.b64decode(h).decode("utf-8") if h else None


class AudioHTTPBot:
    name = "audio-http"

    def __init__(self, base_url: str, version: str = "?", label: str | None = None):
        self.base = base_url.rstrip("/")
        self.version = version
        self.label = label or f"{self.base} ({version})"
        self.capabilities = {"audio_io"}
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    async def _post(self, url: str, **kw) -> tuple[httpx.Response, bytes, float, float]:
        t_send = time.perf_counter()
        t_first = None
        chunks = []
        async with self._http.stream("POST", url, **kw) as r:
            r.raise_for_status()
            async for c in r.aiter_bytes():
                if t_first is None:
                    t_first = time.perf_counter()
                chunks.append(c)
        t_done = time.perf_counter()
        return r, b"".join(chunks), (t_first or t_done) - t_send, t_done - t_send

    def _reply(self, r: httpx.Response, body: bytes, lat: float, tot: float) -> BotReply:
        x, sr = audio.read_wav_bytes(body)
        text = _b64(r.headers.get("x-bot-text"))
        if text is not None:
            self.capabilities.add("exposes_reply_text")
        return BotReply(x, sr, text_true=text, heard_caller=_b64(r.headers.get("x-bot-heard")),
                        end_call=r.headers.get("x-end-call") == "1", response_latency_s=lat, total_s=tot)

    async def start_call(self) -> tuple[str, BotReply]:
        r, body, lat, tot = await self._post(f"{self.base}/call/start")
        return r.headers["x-session-id"], self._reply(r, body, lat, tot)

    async def turn(self, session_id: str, audio_8k: np.ndarray, sr: int, *, reference_text: str | None = None) -> BotReply:
        wav = audio.wav_bytes(audio_8k, sr)
        r, body, lat, tot = await self._post(f"{self.base}/call/{session_id}/turn",
                                             files={"audio": ("turn.wav", wav, "audio/wav")})
        return self._reply(r, body, lat, tot)

    async def end_call(self, session_id: str) -> None:
        try:
            await self._http.post(f"{self.base}/call/{session_id}/end")
        except httpx.HTTPError:
            pass


class TextHTTPBot:
    """Text bot wrapped with the harness's own Prisma (hearing) and Timbre (speaking)."""

    name = "text-http (logic-only)"

    def __init__(self, base_url: str, stt, tts, voice: str | None = None, version: str = "?", label: str | None = None):
        self.base = base_url.rstrip("/")
        self.stt, self.tts, self.voice = stt, tts, voice
        self.version = version
        self.label = label or f"{self.base} ({version}, logic-only)"
        self.capabilities = {"text_io", "exposes_reply_text"}
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    async def _speak(self, text: str) -> tuple[np.ndarray, int]:
        from refbot.pipeline import reply_language
        from .. import voices
        lang = reply_language(text, "v2")
        return await self.tts.synthesize(text or "...", voice=self.voice or voices.refbot_voice(lang), language=lang)

    async def start_call(self) -> tuple[str, BotReply]:
        t0 = time.perf_counter()
        j = (await self._http.post(f"{self.base}/text/start")).raise_for_status().json()
        lat = time.perf_counter() - t0
        x, sr = await self._speak(j["text"])
        return j["session_id"], BotReply(x, sr, text_true=j["text"], response_latency_s=lat, total_s=lat)

    async def turn(self, session_id: str, audio_8k: np.ndarray, sr: int, *, reference_text: str | None = None) -> BotReply:
        heard = await self.stt.transcribe(audio_8k, sr, reference_text=reference_text)
        t0 = time.perf_counter()
        j = (await self._http.post(f"{self.base}/text/{session_id}/turn", json={"text": heard.text})).raise_for_status().json()
        lat = time.perf_counter() - t0
        x, out_sr = await self._speak(j["text"])
        return BotReply(x, out_sr, text_true=j["text"], heard_caller=heard.text, end_call=bool(j.get("end_call")),
                        response_latency_s=lat, total_s=lat)

    async def end_call(self, session_id: str) -> None:
        pass
