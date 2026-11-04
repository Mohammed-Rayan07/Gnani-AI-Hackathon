"""Comment loop: "describe a caller" -> persona -> one call against bot v2 -> verdict -> reel.

Honesty rules:
- Languages Prisma/Timbre don't support are mapped to the nearest supported one,
  and the reply text says so.
- Every reply names the model that actually generated the caller.
- Clips go out in order of arrival, critics included; never tied to likes.
- No real people, voices or identifiers: the safety lint refuses them.
"""

from __future__ import annotations

import json
import re
import unicodedata

import yaml

from . import models
from .clients import build_clients
from .config import get_settings
from .models import Persona

SUPPORTED = {"hi": "Hindi", "en": "English", "bn": "Bengali", "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam",
             "mr": "Marathi", "pa": "Punjabi", "ta": "Tamil", "te": "Telugu"}
NAME_TO_CODE = {v.lower(): k for k, v in SUPPORTED.items()} | {"hinglish": "hi", "tanglish": "ta", "kannad": "kn",
                                                                 "bangla": "bn", "marathi": "mr", "oriya": "or"}
NEAREST = {  # unsupported -> (supported code, why)
    "bhojpuri": ("hi", "Hindi with Bhojpuri words"), "awadhi": ("hi", "Hindi with Awadhi words"),
    "maithili": ("hi", "Hindi with Maithili words"), "magahi": ("hi", "Hindi with Magahi words"),
    "haryanvi": ("hi", "Hindi with Haryanvi words"), "rajasthani": ("hi", "Hindi with Rajasthani words"),
    "marwari": ("hi", "Hindi with Marwari words"), "bundeli": ("hi", "Hindi with Bundeli words"),
    "chhattisgarhi": ("hi", "Hindi with Chhattisgarhi words"), "garhwali": ("hi", "Hindi with Garhwali words"),
    "kumaoni": ("hi", "Hindi with Kumaoni words"), "urdu": ("hi", "Hindustani (Hindi script)"),
    "nepali": ("hi", "Hindi"), "dogri": ("hi", "Hindi"), "kashmiri": ("hi", "Hindi"), "sindhi": ("hi", "Hindi"),
    "odia": ("bn", "Bengali, the nearest supported eastern language"), "oriya": ("bn", "Bengali, the nearest supported eastern language"),
    "assamese": ("bn", "Bengali, the nearest supported eastern language"), "konkani": ("mr", "Marathi with Konkani words"),
    "tulu": ("kn", "Kannada with Tulu words"), "kodava": ("kn", "Kannada"), "bhili": ("gu", "Gujarati"),
    "kutchi": ("gu", "Gujarati with Kutchi words"), "santhali": ("hi", "Hindi"),
}
SCRIPT_FOR = {"hi": "devanagari", "mr": "devanagari", "ta": "tamil", "kn": "kannada", "bn": "bengali", "te": "telugu",
              "ml": "malayalam", "gu": "gujarati", "pa": "gurmukhi", "en": "latin"}


def slug(text: str, n: int = 40) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")[:n] or "caller"


def language_mapping(description: str) -> tuple[list[str], str | None]:
    """Supported codes mentioned, plus an honest note for any unsupported language mentioned."""
    low = description.lower()
    codes, notes = [], []
    for word, (code, why) in NEAREST.items():
        if re.search(rf"\b{word}\b", low):
            notes.append(f"{word.title()} isn't supported by Prisma/Timbre yet, so this caller speaks {why}.")
            codes.append(code)
    for word, code in NAME_TO_CODE.items():
        if code in SUPPORTED and re.search(rf"\b{word}\b", low):
            codes.append(code)
    if "english" in low or "hinglish" in low or "tanglish" in low:
        codes.append("en")
    out = list(dict.fromkeys(codes)) or ["hi", "en"]
    return out, " ".join(dict.fromkeys(notes)) or None


def _voices(language: str | None = None) -> list[str]:
    """Timbre v2.5 voices for `language` (TIMBRE_VOICES, if set, restricts the pool)."""
    import os

    from . import voices
    pool = voices.for_language(language) if language else list(voices.V25)
    allowed = [v.strip() for v in os.environ.get("TIMBRE_VOICES", "").split(",") if v.strip()]
    if allowed:
        pool = [v for v in pool if v in allowed] or [v for v in allowed if v in voices.V25] or pool
    return pool or [voices.DEFAULT_VOICE]


def persona_prompt(description: str, codes: list[str], note: str | None, scenarios: dict) -> list[dict]:
    from . import channel
    schema = {
        "name": "short display name", "summary": "one line", "background": "2 sentences",
        "speaking_style": "how they talk: code-mix ratio, pace, temper, filler words",
        "languages": [f"{c}-IN" for c in codes], "script": "mixed|devanagari|tamil|kannada|bengali|telugu|malayalam|gujarati|gurmukhi|latin",
        "expected_reply_language": "e.g. hi-en, ta-en, hi, kn", "tts_language": f"one of {[c + '-IN' for c in SUPPORTED]}",
        "voice": f"one of {_voices(codes[0] + '-IN')} (pick the gender that fits)", "channel": f"one of {list(channel.PROFILES)}",
        "sample_lines": ["2 short example lines in their voice"], "tactics": ["2-3 behaviours that stress a bot"],
        "scenario": f"one of {list(scenarios)}",
    }
    system = ("You turn a social-media comment describing a phone caller into a persona for testing a FICTIONAL bank's "
              "voice bot. Keep it affectionate, never mocking a community. Never use real people's names, real numbers "
              "or real identifiers. Only these languages are available: " + ", ".join(f"{c}-IN" for c in SUPPORTED) +
              (f". Language note: {note}" if note else "") + "\nReply with ONLY a JSON object with these keys: " + json.dumps(schema, ensure_ascii=False))
    return [{"role": "system", "content": system}, {"role": "user", "content": f"Comment: {description}"}]


def offline_persona(description: str, codes: list[str]) -> dict:
    main = codes[0]
    return {"name": description[:40], "summary": description[:120], "background": description,
            "speaking_style": "as described in the comment", "languages": [f"{c}-IN" for c in codes],
            "script": "mixed" if "en" in codes and main != "en" else SCRIPT_FOR.get(main, "latin"),
            "expected_reply_language": f"{main}-en" if "en" in codes and main != "en" else main,
            "tts_language": f"{main}-IN", "voice": _voices(f"{main}-IN")[0], "channel": "city_4g",
            "sample_lines": [], "tactics": ["repeats the question"], "scenario": "balance_block_card"}


async def build_persona(description: str, llm, scenarios: dict) -> tuple[Persona, str]:
    from . import channel, safety

    problems = safety.find_problems(description)
    if problems:
        raise ValueError("Refusing this caller (synthetic data only): " + "; ".join(problems))
    codes, note = language_mapping(description)
    if getattr(llm, "offline", False):
        d = offline_persona(description, codes)
    else:
        d = await llm.chat_json(persona_prompt(description, codes, note, scenarios), temperature=0.7, max_tokens=900, seed=1)
    scenario_id = d.pop("scenario", None)
    d["id"] = "community_" + slug(description)
    d["channel"] = d.get("channel") if d.get("channel") in channel.PROFILES else "city_4g"
    if d.get("tts_language", "")[:2] not in SUPPORTED:
        d["tts_language"] = f"{codes[0]}-IN"
    pool = _voices(d["tts_language"])
    d["voice"] = d.get("voice") if d.get("voice") in pool else pool[0]
    d["fallback_voice"] = d["voice"]
    d["languages"] = [l for l in d.get("languages", []) if l[:2] in SUPPORTED] or [f"{codes[0]}-IN"]
    d["adversarial"] = False
    d["generated_by"] = llm.label
    d["language_note"] = note
    p = Persona.model_validate(d)
    generated = safety.find_problems(yaml.safe_dump(p.model_dump(), allow_unicode=True))
    if generated:
        raise ValueError("Generated persona failed the safety lint: " + "; ".join(generated))
    return p, (scenario_id if scenario_id in scenarios else "balance_block_card")


async def run_comment_caller(description, scenario_id, bot_spec, seed, want_reel, make_bot, out) -> None:
    from .judge import judge_run
    from .orchestrator import CallSpec, Orchestrator, new_run_id, write_manifest
    from .reel import render_reel

    s = get_settings()
    c = build_clients(s)
    scenarios = models.scenarios()
    persona, picked = await build_persona(description, c.persona_llm, scenarios)
    sc = scenarios[scenario_id or picked]
    bot = make_bot(bot_spec, c)
    run_id = "caller-" + new_run_id(bot.version)
    run_dir = s.runs_dir / run_id
    write_manifest(run_dir, run_id=run_id, bot=bot_spec, bot_label=bot.label, bot_version=bot.version, adapter=bot.name,
                   mode=s.mode_label, personas=[persona.id], scenarios=[sc.id], seeds=1, comment=description,
                   models={"persona": c.persona_llm.label, "bot": c.bot_llm.label, "judge": c.judge_llm.label,
                           "stt": getattr(c.stt, "label", "?"), "tts": s.tts_model})
    (run_dir / "persona.yaml").write_text(yaml.safe_dump(persona.model_dump(), allow_unicode=True, sort_keys=False), encoding="utf-8")
    rec = await Orchestrator(c, bot, run_dir, run_id).run_call(CallSpec(persona, sc, seed, persona.channel))
    use_llm = not s.offline and s.judge_llm.configured
    summary = await judge_run(run_dir, {persona.id: persona}, scenarios, c.judge_llm, use_llm)
    verdict = json.loads((run_dir / "verdicts.json").read_text(encoding="utf-8"))[0]
    for x in (c.stt, c.tts, c.persona_llm, c.bot_llm, c.judge_llm):
        if hasattr(x, "aclose"):
            await x.aclose()
    reel_path = render_reel(run_dir, rec.call_id) if want_reel else None
    failed = [cr["name"].replace("_", " ") for cr in verdict["criteria"] if cr["status"] == "fail"]
    result = "PASSED" if verdict["passed"] else "FAILED (" + ", ".join(failed) + ")"
    reply = (f"Here's {persona.name} calling the bot ({bot.label.split(' (')[0]}) on a {persona.channel.replace('_', ' ')} line: "
             f"{result}. Caller generated by {persona.generated_by}.")
    if persona.language_note:
        reply += " " + persona.language_note
    out(f"\nRun: {run_dir}\nReel: {reel_path}\nJudge: {summary.get('judge_model')}\n\nSuggested reply:\n{reply}")
