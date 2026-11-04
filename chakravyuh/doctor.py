"""`chakravyuh doctor`: verify the whole setup in one go, with a fix hint for every failure.

Costs a few paise of Gnani credits (one ~30-character TTS line, two short STT
clips) and three tiny LLM calls. Never prints keys.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass

import httpx

from . import audio, channel
from .config import ROOT, Settings

TEST_LINE = "नमस्ते, मेरा card block करना है।"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def _mask(v: str) -> str:
    return "missing" if not v else f"set ({len(v)} chars, ends …{v[-3:]})"


def config_checks(s: Settings) -> list[Check]:
    out = [Check(".env file", (ROOT / ".env").exists(), str(ROOT / ".env"),
                 "Copy .env.example to .env in the repo root and fill it in.")]
    out.append(Check("GNANI_API_KEY", bool(s.gnani_api_key), _mask(s.gnani_api_key),
                     "Create a key at app.gnani.ai and put it in .env as GNANI_API_KEY=..."))
    for role in (s.persona_llm, s.bot_llm, s.judge_llm):
        p = role.role.upper()
        out.append(Check(f"{p}_LLM", role.configured,
                         f"{role.model or '-'} @ {role.base_url or '-'} · key {_mask(role.api_key)}",
                         f"Set {p}_LLM_BASE_URL and {p}_LLM_MODEL (and _API_KEY) in .env."))
    same = s.judge_llm.configured and s.judge_llm.model == s.bot_llm.model and s.judge_llm.base_url == s.bot_llm.base_url
    out.append(Check("judge differs from bot", not same,
                     "different models" if not same else f"both are {s.bot_llm.model}",
                     "Use a different model family for JUDGE_LLM (e.g. Groq) than BOT_LLM (e.g. Gemini)."))
    out.append(Check("ffmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "not on PATH",
                     "Install ffmpeg (Windows: winget install Gyan.FFmpeg) and reopen the terminal."))
    return out


async def gnani_checks(s: Settings, clients) -> list[Check]:
    out: list[Check] = []
    try:
        t0 = time.perf_counter()
        x, sr = await clients.tts.synthesize(TEST_LINE, voice="Pranav", language="hi-IN")
        out.append(Check("Timbre TTS", len(x) > sr * 0.5, f"{len(x) / sr:.1f}s of audio @ {sr} Hz in {time.perf_counter() - t0:.1f}s"))
    except Exception as e:  # noqa: BLE001 - every failure becomes a readable hint
        out.append(Check("Timbre TTS", False, str(e)[:300],
                         "401/403: check GNANI_API_KEY. 400/422: paste me the error (voice/model/field names). "
                         "Timeout/DNS: check your internet."))
        return out
    s.runs_dir.mkdir(parents=True, exist_ok=True)
    audio.write_wav(s.runs_dir / "doctor_tts.wav", x, sr)
    try:
        r16 = await clients.stt.transcribe(x, sr)
        out.append(Check("Prisma STT (16 kHz)", bool(r16.text), f"heard: {r16.text!r} · lang {r16.detected_language}"))
    except Exception as e:  # noqa: BLE001
        out.append(Check("Prisma STT (16 kHz)", False, str(e)[:300], "Paste me this error: it tells me which field Prisma wants."))
        return out
    line = channel.degrade(x, sr, "city_4g", seed=1)
    try:
        before = clients.stt.upload_sr
        r8 = await clients.stt.transcribe(line.audio, line.sr)
        note = " (Prisma rejected 8 kHz; uploads now upsampled to 16 kHz automatically)" if clients.stt.upload_sr != before else ""
        out.append(Check("Prisma STT (8 kHz noisy line)", bool(r8.text), f"heard: {r8.text!r}{note}"))
    except Exception as e:  # noqa: BLE001
        out.append(Check("Prisma STT (8 kHz noisy line)", False, str(e)[:300], "Set PRISMA_UPLOAD_SR=16000 in .env and re-run."))
    return out


async def llm_checks(s: Settings, clients) -> list[Check]:
    out = []
    for role, client in (("persona", clients.persona_llm), ("bot", clients.bot_llm), ("judge", clients.judge_llm)):
        if not getattr(client, "role", None) or not client.role.configured:
            continue
        try:
            t0 = time.perf_counter()
            j = await client.chat_json([{"role": "user", "content": 'Reply with ONLY this JSON: {"ok": true, "word": "नमस्ते"}'}],
                                       max_tokens=200)
            out.append(Check(f"{role} LLM", j.get("ok") is True, f"{client.label}: {json.dumps(j, ensure_ascii=False)} in {time.perf_counter() - t0:.1f}s"
                             + (" (JSON mode unsupported, handled)" if client._drop_json else "")))
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            hint = ("401/403: wrong API key. 404: wrong model id or base URL (check the provider's model list). "
                    "429: free-tier limit, wait a minute.")
            out.append(Check(f"{role} LLM", False, msg[:300], hint))
    return out


async def network_checks(s: Settings) -> list[Check]:
    urls = {"Gnani API": s.gnani_base_url}
    for role in (s.persona_llm, s.bot_llm, s.judge_llm):
        if role.base_url:
            urls[f"{role.role} LLM host"] = role.base_url
    out = []
    async with httpx.AsyncClient(timeout=10) as h:
        for name, url in urls.items():
            try:
                r = await h.get(url)
                out.append(Check(f"reach {name}", True, f"{url} → HTTP {r.status_code}"))
            except httpx.HTTPError as e:
                out.append(Check(f"reach {name}", False, f"{url}: {type(e).__name__}", "Check internet / VPN / firewall."))
    return out
