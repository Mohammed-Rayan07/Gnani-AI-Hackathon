"""Runs simulated phone calls.

One turn:
  persona LLM -> text -> Timbre (or cloned voice) -> upstream line (noise, 8 kHz, codec, loss)
  -> bot -> bot audio -> VAD timing on the bot's own audio -> downstream line
  -> Prisma -> what the caller heard -> back into the persona LLM.
Everything is saved under runs/<run_id>/calls/<call_id>/ for the judge and the scorecard.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import audio, channel, vad
from .clients import Clients
from .models import CallRecord, Persona, Scenario, Turn, TurnTiming
from .persona_engine import PersonaEngine

log = logging.getLogger("chakravyuh.run")


@dataclass
class CallSpec:
    persona: Persona
    scenario: Scenario
    seed: int
    channel: str


def call_id(spec: CallSpec) -> str:
    return f"{spec.persona.id}__{spec.scenario.id}__s{spec.seed}__{spec.channel}"


def new_run_id(bot_version: str) -> str:
    return f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{bot_version}-{uuid.uuid4().hex[:4]}"


def estimate_cost(clients: Clients, specs: list[CallSpec], bot_is_ours: bool) -> float:
    """Rough upper estimate in credits/INR: ~6 turns/call, cache hits ignored."""
    r = clients.ledger.rates
    per_turn = r.tts(90) + r.stt(6.0)                    # caller TTS + harness STT of the bot
    if bot_is_ours:
        per_turn += r.stt(4.0) + r.tts(160)              # the reference bot's own STT + TTS
    total = 0.0
    for s in specs:
        total += per_turn * min(6, s.scenario.max_turns) + r.tts(120) + r.stt(6.0)   # + greeting
    return round(total, 2)


class Orchestrator:
    def __init__(self, clients: Clients, bot, run_dir: Path, run_id: str):
        self.c = clients
        self.bot = bot
        self.run_dir = run_dir
        self.run_id = run_id
        self.persona_engine = PersonaEngine(clients.persona_llm)
        self._clone_fallback_noted: set[str] = set()

    async def _caller_audio(self, p: Persona, text: str) -> tuple[np.ndarray, int, str]:
        voice = p.voice
        if voice.startswith("clone:") and not (self.c.settings.voices_dir / f"{voice[6:]}.json").exists():
            if voice not in self._clone_fallback_noted:
                log.warning("voice %s has no embedding yet; using fallback voice %s (reported on the scorecard)", voice, p.fallback_voice)
                self._clone_fallback_noted.add(voice)
            voice = p.fallback_voice
        if self.c.settings.offline:
            voice = voice.replace("clone:", "")
        x, sr = await self.c.tts.synthesize(text, voice=voice, language=p.tts_language)
        return x, sr, voice

    async def run_call(self, spec: CallSpec) -> CallRecord:
        cid = call_id(spec)
        cdir = self.run_dir / "calls" / cid
        cdir.mkdir(parents=True, exist_ok=True)
        rec = CallRecord(
            call_id=cid, run_id=self.run_id, persona_id=spec.persona.id, scenario_id=spec.scenario.id,
            seed=spec.seed, channel=spec.channel, bot_label=self.bot.label, bot_version=self.bot.version,
            mode=self.c.settings.mode_label, adapter=self.bot.name,
            models={"persona": self.c.persona_llm.label, "stt": getattr(self.c.stt, "label", "?"),
                    "bot": self.bot.label},
        )
        heard: list[tuple[str, str]] = []
        sid = None
        try:
            sid, greet = await self.bot.start_call()
            t0, down0 = self._bot_side(cdir, 0, "", greet, spec)
            rec.turns.append(t0)
            await self._finish_turn_stt(t0, down0, heard)      # the caller hears the greeting first
            for i in range(1, spec.scenario.max_turns + 1):
                ct = await self.persona_engine.next_turn(spec.persona, spec.scenario, heard, spec.seed, i)
                x, sr, used_voice = await self._caller_audio(spec.persona, ct.utterance)
                rec.models.setdefault("caller_voice", self.c.tts.label(used_voice))
                up = channel.degrade(x, sr, spec.channel, seed=spec.seed * 1000 + i * 2)
                audio.write_wav(cdir / f"t{i:02d}_caller_clean.wav", x, sr)
                audio.write_wav(cdir / f"t{i:02d}_caller_line.wav", up.audio, up.sr)
                heard.append(("caller", ct.utterance))
                reply = await self.bot.turn(sid, up.audio, up.sr, reference_text=ct.utterance)
                turn, down = self._bot_side(cdir, i, ct.utterance, reply, spec, caller_meta=up.meta)
                turn.caller_intent, turn.caller_lang = ct.intent, ct.lang
                turn.audio.update({"caller_clean": f"t{i:02d}_caller_clean.wav", "caller_line": f"t{i:02d}_caller_line.wav"})
                rec.turns.append(turn)
                await self._finish_turn_stt(turn, down, heard)
                if reply.end_call:
                    rec.ended_by = "bot"
                    break
                if ct.end_call:
                    rec.ended_by = "caller"
                    break
            else:
                rec.ended_by = "turn_cap"
        except Exception as e:  # a crashed call is recorded, never silently dropped
            rec.ended_by = "error"
            rec.error = f"{type(e).__name__}: {e}"
            log.error("call %s failed: %s\n%s", cid, e, traceback.format_exc(limit=3))
        finally:
            if sid is not None:
                await self.bot.end_call(sid)
        (cdir / "call.json").write_text(rec.model_dump_json(indent=1), encoding="utf-8")
        return rec

    def _bot_side(self, cdir, i, caller_text, reply, spec, caller_meta=None) -> tuple[Turn, channel.ChannelResult | None]:
        turn = Turn(index=i, caller_text=caller_text, bot_text_true=reply.text_true,
                    bot_heard_caller=reply.heard_caller, bot_end_call=reply.end_call)
        down = None
        if caller_meta:
            turn.channel_meta["upstream"] = caller_meta
        if reply.audio is not None and len(reply.audio):
            tm = vad.timing(reply.audio, reply.sr)
            turn.timing = TurnTiming(response_latency_s=reply.response_latency_s, total_s=reply.total_s,
                                     leading_silence_s=tm.leading_silence_s, max_internal_gap_s=tm.max_internal_gap_s,
                                     bot_speech_s=tm.speech_s)
            down = channel.degrade(reply.audio, reply.sr, spec.channel, seed=spec.seed * 1000 + i * 2 + 1, ambient=False)
            audio.write_wav(cdir / f"t{i:02d}_bot_raw.wav", reply.audio, reply.sr)
            audio.write_wav(cdir / f"t{i:02d}_bot_line.wav", down.audio, down.sr)
            turn.audio.update({"bot_raw": f"t{i:02d}_bot_raw.wav", "bot_line": f"t{i:02d}_bot_line.wav"})
            turn.channel_meta["downstream"] = down.meta
        return turn, down

    async def _finish_turn_stt(self, turn: Turn, down: channel.ChannelResult | None, heard: list) -> None:
        if down is None:
            heard.append(("bot", ""))
            return
        res = await self.c.stt.transcribe(down.audio, down.sr, reference_text=turn.bot_text_true)
        turn.bot_text_heard = res.text
        turn.bot_detected_lang = res.detected_language
        heard.append(("bot", res.text))

    async def run_matrix(self, specs: list[CallSpec], concurrency: int, on_done=None) -> list[CallRecord]:
        sem = asyncio.Semaphore(concurrency)

        async def one(spec):
            async with sem:
                rec = await self.run_call(spec)
                if on_done:
                    on_done(rec)
                return rec

        return list(await asyncio.gather(*(one(s) for s in specs)))


def write_manifest(run_dir: Path, **info) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps(info, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def load_calls(run_dir: Path) -> list[CallRecord]:
    return [CallRecord.model_validate_json(p.read_text(encoding="utf-8"))
            for p in sorted((run_dir / "calls").glob("*/call.json"))]
