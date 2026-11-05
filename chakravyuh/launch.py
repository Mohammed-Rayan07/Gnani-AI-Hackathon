"""`chakravyuh launch`: the whole live pipeline in one resumable command.

doctor -> clone -> run v1 -> run v2 -> judge -> reels -> site -> results -> kit -> video -> evon

- Fixed run folders (runs/launch-v1, runs/launch-v2) make every step resumable:
  finished calls are skipped, crashed calls (e.g. an exhausted free-tier quota) are retried.
- Every number written to RESULTS.md, the README, the launch kit and the demo video
  is read from the judged runs' summary.json / verdicts.json. Nothing is estimated.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import models
from .clients import Clients, build_clients
from .config import ROOT, Settings
from .orchestrator import CallSpec, Orchestrator, estimate_cost, write_manifest

ALL_STEPS = ["doctor", "clone", "run", "judge", "reels", "site", "results", "kit", "video", "evon"]
DEFAULT_PERSONAS = ["uncle_traffic", "tamil_aunty", "farmer_2g", "social_engineer", "kannada_auto"]
CRIT_HUMAN = {
    "pii_leak": "leaked a (fake) identifier", "language_match": "answered in the wrong language",
    "latency_dead_air": "too slow / dead air", "bot_repetition": "got stuck repeating itself",
    "call_completed": "crashed", "task_success": "didn't finish the caller's task",
    "hallucination": "made something up", "policy_adherence": "broke bank policy",
    "recovery": "didn't recover from a garbled turn", "social_engineering_resistance": "fell for social engineering",
}


@dataclass
class LaunchConfig:
    personas: list[str] = field(default_factory=lambda: list(DEFAULT_PERSONAS))
    scenarios: list[str] = field(default_factory=list)          # empty = all
    seeds: int = 3
    max_turns: int = 6
    clone_wav: Path | None = None
    consent: bool = False
    steps: list[str] = field(default_factory=lambda: list(ALL_STEPS))
    yes: bool = False
    retries: int = 2
    site_dir: Path = ROOT / "site"
    kit_dir: Path = ROOT / "launch"

    def run_dir(self, s: Settings, version: str) -> Path:
        return s.runs_dir / f"launch-{version}"


# ----------------------------------------------------------------------------- run (resumable)

def build_specs(cfg: LaunchConfig) -> list[CallSpec]:
    P, S = models.personas(), models.scenarios()
    sids = cfg.scenarios or list(S)
    specs = []
    for pid in cfg.personas:
        if pid not in P:
            raise ValueError(f"unknown persona {pid}; have {list(P)}")
        for sid in sids:
            sc = S[sid].model_copy(update={"max_turns": cfg.max_turns}) if cfg.max_turns else S[sid]
            for seed in range(1, cfg.seeds + 1):
                specs.append(CallSpec(P[pid], sc, seed, P[pid].channel))
    return specs


def _done_ids(run_dir: Path) -> set[str]:
    out = set()
    for p in (run_dir / "calls").glob("*/call.json"):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("ended_by") != "error":
                out.add(p.parent.name)
        except (OSError, json.JSONDecodeError):
            pass
    return out


async def run_version(c: Clients, version: str, run_dir: Path, specs: list[CallSpec], log) -> list[str]:
    from .adapters.inprocess import InProcessRefBot
    from .orchestrator import call_id

    bot = InProcessRefBot(version, c.stt, c.tts, c.bot_llm)
    todo = [sp for sp in specs if call_id(sp) not in _done_ids(run_dir)]
    if not (run_dir / "manifest.json").exists():
        write_manifest(run_dir, run_id=run_dir.name, bot=f"inprocess:{version}", bot_label=bot.label, bot_version=version,
                       adapter=bot.name, mode=c.settings.mode_label,
                       personas=sorted({sp.persona.id for sp in specs}), scenarios=sorted({sp.scenario.id for sp in specs}),
                       seeds=max(sp.seed for sp in specs), max_turns=specs[0].scenario.max_turns, tag="launch",
                       models={"persona": c.persona_llm.label, "bot": c.bot_llm.label, "judge": c.judge_llm.label,
                               "stt": getattr(c.stt, "label", "?"),
                               "tts": "offline-tts" if c.settings.offline else c.settings.tts_model})
    log(f"  {version}: {len(specs) - len(todo)}/{len(specs)} calls already done, running {len(todo)}")
    if todo:
        orch = Orchestrator(c, bot, run_dir, run_dir.name)
        n = [0]

        def tick(rec):
            n[0] += 1
            st = "ERROR " + (rec.error or "")[:120] if rec.ended_by == "error" else f"{len(rec.turns) - 1} turns, ended by {rec.ended_by}"
            log(f"    [{n[0]}/{len(todo)}] {rec.call_id}: {st}")

        await orch.run_matrix(todo, c.settings.concurrency, on_done=tick)
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    usage = m.get("llm_usage", {})
    for role, x in (("persona", c.persona_llm), ("bot", c.bot_llm)):
        u = getattr(x, "usage", None)
        if u:
            prev = usage.get(role, {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0})
            usage[role] = {k: prev.get(k, 0) + u[k] for k in u}
            for k in u:
                u[k] = 0
    m["llm_usage"] = usage
    log(f"  {version} LLM usage so far: " + ", ".join(
        f"{r} {u['requests']} req / {u['prompt_tokens'] + u['completion_tokens']:,} tokens" for r, u in usage.items()))
    (run_dir / "manifest.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    return sorted({call_id(sp) for sp in todo} - _done_ids(run_dir))       # still-crashed calls


# ----------------------------------------------------------------------------- reels

def _verdicts(run_dir: Path, tag: str = "") -> list[dict]:
    p = run_dir / f"verdicts{'.' + tag if tag else ''}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _crit(v: dict, name: str) -> str | None:
    return next((c["status"] for c in v["criteria"] if c["name"] == name), None)


def pick_reels(v1_dir: Path, v2_dir: Path) -> dict[str, tuple[Path, str]]:
    """Choose the clips the launch needs, by priority. Only real verdicts drive the choice."""
    v1, v2 = _verdicts(v1_dir), _verdicts(v2_dir)
    picks: dict[str, tuple[Path, str]] = {}

    def first(vs, run_dir, pred, prefer=()):
        cands = [v for v in vs if pred(v)]
        cands.sort(key=lambda v: (min((i for i, p in enumerate(prefer) if p in v["call_id"]), default=99), v["seed"]))
        return (run_dir, cands[0]["call_id"]) if cands else None

    for name, got in (
        ("leak", first(v1, v1_dir, lambda v: _crit(v, "pii_leak") == "fail", ("social_engineer__kyc", "kyc_otp", "social_engineer"))),
        ("language", first(v1, v1_dir, lambda v: _crit(v, "language_match") == "fail", ("uncle_traffic", "tamil_aunty", "kannada_auto"))),
        ("rural_2g", first(v1 + v2, v1_dir, lambda v: "rural_2g" in v["call_id"] and not v["passed"]) or
         first(v1, v1_dir, lambda v: "rural_2g" in v["call_id"])),
        ("still_failing", first(v2, v2_dir, lambda v: v["failure_kind"] == "bot", ("kyc_otp", "uncle_traffic"))),
        ("fixed", first(v2, v2_dir, lambda v: v["passed"], ("social_engineer__kyc", "kyc_otp", "uncle_traffic"))),
    ):
        if got:
            picks[name] = got
    # the rural_2g pick may come from v2: fix its run folder
    if "rural_2g" in picks and not (picks["rural_2g"][0] / "calls" / picks["rural_2g"][1]).exists():
        picks["rural_2g"] = (v2_dir, picks["rural_2g"][1])
    return picks


def render_reels(picks: dict[str, tuple[Path, str]], log) -> dict[str, dict[str, Path]]:
    from .reel import render_reel

    out: dict[str, dict[str, Path]] = {}
    for name, (run_dir, cid) in picks.items():
        out[name] = {}
        for aspect in ("4:5", "9:16", "16:9"):
            try:
                out[name][aspect] = render_reel(run_dir, cid, aspect=aspect)
            except Exception as e:  # noqa: BLE001 - a reel failure must not stop the launch
                log(f"    reel {name} {aspect} failed: {e}")
        log(f"    reel {name}: {cid}")
    return out


# ----------------------------------------------------------------------------- numbers

def _summary(run_dir: Path, tag: str = "") -> dict:
    p = run_dir / f"summary{'.' + tag if tag else ''}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def facts(v1_dir: Path, v2_dir: Path) -> dict:
    """Every number the public copy may use, read from the judged runs."""
    s1, s2 = _summary(v1_dir), _summary(v2_dir)
    m1 = json.loads((v1_dir / "manifest.json").read_text(encoding="utf-8"))
    vs1, vs2 = _verdicts(v1_dir), _verdicts(v2_dir)

    def leaks(vs):
        return sum(1 for v in vs if _crit(v, "pii_leak") == "fail")

    def fails_by_crit(vs):
        out: dict[str, int] = {}
        for v in vs:
            for c in v["criteria"]:
                if c["status"] == "fail":
                    out[c["name"]] = out.get(c["name"], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    still = []
    for v in vs2:
        if v["failure_kind"] != "bot":
            continue
        for c in v["criteria"]:
            if c["status"] == "fail":
                ev = (c.get("evidence") or [{}])[0]
                still.append({"call_id": v["call_id"], "persona": v["persona_id"], "scenario": v["scenario_id"],
                              "criterion": c["name"], "what": CRIT_HUMAN.get(c["name"], c["name"]),
                              "quote": ev.get("quote", ""), "reason": c.get("reason", "")})
    still_counts: dict[str, int] = {}
    for x in still:
        still_counts[x["criterion"]] = still_counts.get(x["criterion"], 0) + 1
    top_still = max(still_counts, key=still_counts.get) if still_counts else None

    agreement = {}
    for d in (v1_dir, v2_dir):
        p = d / "agreement.primary.evon.json"
        if p.exists():
            agreement[d.name] = json.loads(p.read_text(encoding="utf-8"))
    human = {}
    for d in (v1_dir, v2_dir):
        p = d / "kappa.json"
        if p.exists():
            human[d.name] = json.loads(p.read_text(encoding="utf-8"))

    return {
        "offline": "OFFLINE" in m1.get("mode", ""),
        "models": m1.get("models", {}), "judge_model": s1.get("judge_model"),
        "calls_total": s1.get("calls", 0) + s2.get("calls", 0),
        "calls_v1": s1.get("calls", 0), "calls_v2": s2.get("calls", 0),
        "errors": (s1.get("errors") or []) + (s2.get("errors") or []),
        "cells_total": s1.get("cells_total", 0),
        "v1_cells": s1.get("cells_passed", 0), "v2_cells": s2.get("cells_passed", 0),
        "v1_rate": s1.get("call_pass_rate"), "v2_rate": s2.get("call_pass_rate"),
        "v1_ci": s1.get("call_pass_ci95"), "v2_ci": s2.get("call_pass_ci95"),
        "v1_leaks": leaks(vs1), "v2_leaks": leaks(vs2),
        "v1_latency": s1.get("latency_to_first_word_s", {}), "v2_latency": s2.get("latency_to_first_word_s", {}),
        "noise": s1.get("harness_noise_cer", {}),
        "v1_fails": fails_by_crit(vs1), "v2_fails": fails_by_crit(vs2),
        "harness_errors": (s1.get("failure_kinds", {}).get("harness", 0) + s2.get("failure_kinds", {}).get("harness", 0)),
        "still_failing": still, "top_still": top_still, "top_still_human": CRIT_HUMAN.get(top_still or "", top_still),
        "evon_agreement": agreement, "human_kappa": human,
        "personas": m1.get("personas", []), "seeds": m1.get("seeds"), "max_turns": m1.get("max_turns"),
        "llm_usage": {"v1": m1.get("llm_usage", {}),
                      "v2": json.loads((v2_dir / "manifest.json").read_text(encoding="utf-8")).get("llm_usage", {})},
    }


def _pct(x) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def _ci(c) -> str:
    return "–" if not c else f"{c[0] * 100:.0f}–{c[1] * 100:.0f}%"


def results_table(f: dict) -> str:
    def lat(d):
        return "–" if not d or d.get("p50") is None else f"{d['p50']}s / {d['p90']}s"

    hk = next(iter(f["human_kappa"].values()), {}) if f["human_kappa"] else {}
    ek = next(iter(f["evon_agreement"].values()), {}) if f["evon_agreement"] else {}
    rows = [
        ("Scenarios passed (≥2/3 seeds)", f"{f['v1_cells']}/{f['cells_total']}", f"{f['v2_cells']}/{f['cells_total']}"),
        ("Call pass rate (95% CI)", f"{_pct(f['v1_rate'])} ({_ci(f['v1_ci'])})", f"{_pct(f['v2_rate'])} ({_ci(f['v2_ci'])})"),
        ("Calls leaking a fake identifier", str(f["v1_leaks"]), str(f["v2_leaks"])),
        ("p50 / p90 time to first word", lat(f["v1_latency"]), lat(f["v2_latency"])),
    ]
    out = ["| | v1 | v2 |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in rows]
    out.append(f"| Judge vs human κ | {hk.get('cohens_kappa', 'pending')} (n={hk.get('labelled', 0)}) | |" if hk
               else "| Judge vs human κ | pending (`chakravyuh label`) | |")
    if ek:
        out.append(f"| Judge vs Evon v3.3 κ | {ek.get('kappa')} (n={ek.get('calls')}) | |")
    return "\n".join(out)


def write_results(f: dict, out: Path) -> Path:
    lines = ["# Results", ""]
    if f["offline"]:
        lines += ["> **OFFLINE DRY RUN.** Simulated speech and scripted callers: these numbers only prove the pipeline runs.", ""]
    lines += [
        f"Matrix: {len(f['personas'])} callers × 3 scenarios × {f['seeds']} seeds × 2 bot versions = **{f['calls_total']} calls** "
        f"(max {f['max_turns']} caller turns each). Judge: **{f['judge_model']}**. Callers: {f['models'].get('persona')}. "
        f"Bot brain: {f['models'].get('bot')}. STT: {f['models'].get('stt')}. TTS: {f['models'].get('tts')}.", "",
        results_table(f), "",
        "## What failed most", "", "| Criterion | v1 fails | v2 fails |", "|---|---|---|",
    ]
    for k in sorted(set(f["v1_fails"]) | set(f["v2_fails"]), key=lambda k: -f["v1_fails"].get(k, 0)):
        lines.append(f"| {k} | {f['v1_fails'].get(k, 0)} | {f['v2_fails'].get(k, 0)} |")
    lines += ["", "## Harness noise floor (how badly Prisma mishears the bot through each line)", "",
              "| Line | phonetic CER (mean) | raw CER | bot turns |", "|---|---|---|---|"]
    for ch, n in f["noise"].items():
        lines.append(f"| {ch} | {_pct(n.get('mean'))} | {_pct(n.get('raw_mean'))} | {n.get('turns')} |")
    lines += ["", f"Harness errors (failures that vanish when judged on the bot's real text): {f['harness_errors']}.", ""]
    lines += ["## What v2 still gets wrong", ""]
    if f["still_failing"]:
        for x in f["still_failing"][:8]:
            q = x["quote"].replace("\n", " ")[:160]
            lines.append(f"- **{x['persona']} × {x['scenario']}**: {x['what']}." + (f" “{q}”" if q else ""))
    else:
        lines.append("- Nothing in this matrix. That says more about the matrix than about the bot: add harder callers.")
    if f["errors"]:
        lines += ["", f"Calls that crashed and were excluded from scoring (re-run `chakravyuh launch` to resume): {len(f['errors'])}."]
    if f["evon_agreement"]:
        lines += ["", "## Second judge: Evon v3.3", ""]
        for run, a in f["evon_agreement"].items():
            lines.append(f"- {run}: agreement {_pct(a.get('agreement'))}, κ = {a.get('kappa')} over {a.get('calls')} calls "
                         f"({a.get('judge_a')} vs {a.get('judge_b')}).")
    lines += ["", "## LLM usage", "", "```", json.dumps(f["llm_usage"], indent=1), "```", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


README_START, README_END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def update_readme(f: dict, readme: Path = ROOT / "README.md") -> bool:
    text = readme.read_text(encoding="utf-8")
    if README_START not in text:
        return False
    block = (f"{README_START}\n" + ("> Offline dry run, not real results.\n\n" if f["offline"] else "")
             + results_table(f) + f"\n\nFull breakdown: [docs/RESULTS.md](docs/RESULTS.md).\n{README_END}")
    text = re.sub(re.escape(README_START) + r".*?" + re.escape(README_END), lambda _: block, text, flags=re.S)
    readme.write_text(text, encoding="utf-8")
    return True


# ----------------------------------------------------------------------------- launch kit

CALLER_PHRASES = {
    "uncle_traffic": "a Hinglish uncle shouting over traffic", "tamil_aunty": "a Tamil-English aunty",
    "farmer_2g": "a farmer on a breaking 2G line", "kannada_auto": "a Kannada auto driver",
    "social_engineer": 'a "bank officer" fishing for a (fake) OTP',
}
TAG_PLACEHOLDER = "[tag Gnani AI's company page here]"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _judge_name(model: str | None) -> str:
    if not model or model.startswith("deterministic"):
        return "an LLM judge"
    return model.split("/")[-1]                     # "openai/gpt-oss-120b" -> "gpt-oss-120b"


def write_kit(f: dict, kit_dir: Path, repo_url: str, site_url: str, cloned: bool = False) -> list[Path]:
    """Every claim is conditional on what actually ran: the caller list comes from the run's
    personas, and the cloned-voice line only appears if voices/me.json exists."""
    kit_dir.mkdir(parents=True, exist_ok=True)
    n = f["calls_total"]
    judge = _judge_name(f["judge_model"])
    order = sorted(f["personas"], key=lambda p: DEFAULT_PERSONAS.index(p) if p in DEFAULT_PERSONAS else 99)
    callers = _join([CALLER_PHRASES.get(p, p.replace("_", " ")) for p in order]) if order else "synthetic callers"
    clone_line = " The uncle is me, cloned with Gnani's Timbre." if cloned and "uncle_traffic" in f["personas"] else ""
    clone_short = " The uncle is my own voice, cloned with Timbre." if clone_line else ""
    ek = next(iter(f["evon_agreement"].values()), None) if f["evon_agreement"] else None
    hk = next(iter(f["human_kappa"].values()), None) if f["human_kappa"] else None
    still = f["top_still_human"] or "nothing in this matrix (so I'm adding harder callers)"
    trust = (f"I hand-checked {hk['labelled']} calls: the judge agreed with me κ = {hk['cohens_kappa']}." if hk else
             f"a second judge, Gnani's own Evon v3.3, agreed with it κ = {ek['kappa']} over {ek['calls']} calls." if ek else
             "an LLM judge isn't ground truth, so every verdict has to quote the exact words, and the code checks the quote exists.")
    banner = "<!-- OFFLINE DRY RUN NUMBERS: DO NOT POST -->\n\n" if f["offline"] else ""
    post = f"""{banner}I made {n} phone calls to a voice bot. Not one of the callers was real.

A voice bot that sounds great in a demo can fall apart on a real call: an uncle shouting over traffic, a farmer on a breaking 2G line, someone switching Tamil to English mid-sentence.

So I built CHAKRAVYUH. Synthetic Indian callers phone a voice bot over a simulated noisy 8 kHz line, and a scorecard comes back with the failure audio.

The callers: {callers}.{clone_line}

How it works:
→ Timbre voices the callers
→ a phone-line simulator adds 8 kHz, noise and packet loss
→ Prisma transcribes the bot through that same bad line
→ {judge} judges task success, hallucination, PII leaks, language match and dead air, and must quote the exact words as evidence

My first-draft bot passed {f['v1_cells']} of {f['cells_total']} scenarios and read out a fake account number in {f['v1_leaks']} calls. The hardened v2 passes {f['v2_cells']} of {f['cells_total']}, with {f['v2_leaks']} leaks.

The honest part: v2 still {still}. And {trust}

All data is synthetic. No real numbers, Aadhaar, PAN or recordings.

Your turn: describe a caller in the comments (e.g. "my dadi who only speaks Marathi and hangs up if you're slow"). CHAKRAVYUH will build them, call the bot, and I'll reply with the clip of what happened.

#GreatIndianAIInternshipChallenge #GnaniAI #VoiceAI
{TAG_PLACEHOLDER}
"""
    first_comment = f"""Repo (code, line simulator, judge rules, limitations): {repo_url}
Scorecards + "hear it fail" audio: {site_url}
Feedback welcome, especially from anyone who's run bots on real telephony."""
    x_thread = f"""{banner}1/ I made {n} phone calls to a voice bot. Not one of the callers was real. 🧵 [video] #GreatIndianAIInternshipChallenge #GnaniAI @GnaniAI
2/ Voice bot demos run on clean audio. Indian phone lines are 8 kHz, noisy, code-mixed and full of interruptions.
3/ The callers: {callers}.{clone_short}
4/ Prisma transcribes the bot through the same bad line. {judge} judges and must quote exact words as evidence. Output: a scorecard with the failure audio.
5/ Bot v1: {f['v1_cells']}/{f['cells_total']} scenarios, {f['v1_leaks']} calls leaked a fake account number. v2: {f['v2_cells']}/{f['cells_total']}, {f['v2_leaks']} leaks.
6/ Still failing: v2 {still}. {trust[0].upper() + trust[1:]}
7/ All synthetic. Code: {repo_url} · Audio: {site_url}. Reply with a caller you want me to build; I'll run them against the bot and reply with the clip.
"""
    replies = """# Comment-loop replies

For each caller request, in order of arrival (critics included, never tied to likes):

    uv run chakravyuh caller "<their description>"

The command prints a ready reply and a reel path. Attach the 4:5 reel to your reply.

If they ask for a real name, number or voice:
> I can only build synthetic callers: no real names, numbers or voices. Describe them without those and I'll make them call the bot!

If they ask for an unsupported language, the generated reply already explains the mapping (e.g. Bhojpuri becomes Hindi with Bhojpuri words).

If they ask "can you test my bot?":
> Happy to, free. If it speaks the audio-http contract in the README I'll run the non-adversarial callers against it, but only with your OK, and I'll share the scorecard with you first.
"""
    followups = f"""# Follow-up posts (link back to the launch post; never nominate these)

1. "Why my first scorecard was wrong": the call-loop bug the first live run exposed. Simulated callers never hung up, so the turn cap was blamed on the bot. Fixed with a hang-up rule and a repetition check.
2. "What a 2G line does to speech recognition": the noise-floor table (phonetic CER per line profile) and the 2G clip where Prisma switched language.
3. Carousel, "7 ways Indian voice bots fail on real phone lines": use the top criteria from docs/RESULTS.md ({', '.join(list(f['v1_fails'])[:7])}).
4. "Your callers so far": a montage of comment-loop reels (credit commenters by name only with their OK).
"""
    teaser = f"""{banner}Every voice bot demo I've seen works on a quiet laptop mic.

Real Indian callers are on a 2G line with a bus behind them, switching from Hindi to English mid-sentence. Some of them are scammers.

So I built something that phones voice bots the way those people do: synthetic callers on a simulated noisy 8 kHz line, built on Gnani's Prisma and Timbre.{" One of the callers is my own cloned voice." if clone_line else ""}

Tomorrow I'll show what broke.

What's the worst thing a customer-care bot has done to you?

#GreatIndianAIInternshipChallenge #GnaniAI
{TAG_PLACEHOLDER}

(Post this the evening before the launch. Don't nominate it: nominate the launch post.)
"""
    models_used = "Prisma v3.0 (speech-to-text), Timbre v2.5 (text-to-speech)" + \
        (", Gnani voice cloning (vachana-vc-v1)" if clone_line else "") + \
        (", Evon v3.3 (second judge)" if ek else "")
    submission = f"""{banner}# Submission form answers (copy field by field)

Submit by 8 Nov; the deadline is 10 Nov, 11:59 PM IST. Check that both nominated posts are live, with both hashtags and the Gnani tag.

| Field | Answer |
|---|---|
| Project title | CHAKRAVYUH: crash-test dummies for Indian voice bots |
| One-line pitch | Synthetic Indian callers phone a voice bot over a simulated noisy 8 kHz line; every failure comes back with audio proof. |
| Problem | Voice bots are tested on clean audio, but Indian callers are on noisy, code-mixed phone lines, and some are social engineers. Bots that pass demos fail real calls and leak data. |
| Target users | Voice-bot teams at banks, telecoms and BPOs; developers building voice agents (it runs as a CI regression gate). |
| What it does | {callers}, calling a reference bank bot; Prisma hears the bot through the same bad line; deterministic checks plus an LLM judge with machine-verified quotes score every call; scorecard, v1→v2 diff, crash reels. |
| Results | {n} calls. First-draft bot: {f['v1_cells']}/{f['cells_total']} scenarios, {f['v1_leaks']} calls leaked a fake account number. Hardened bot: {f['v2_cells']}/{f['cells_total']}, {f['v2_leaks']} leaks. Still failing: {still}. |
| Gnani models used | {models_used} |
| Other tools | Python, numpy/scipy (phone-line simulator), ffmpeg, FastAPI, {judge} as the primary judge |
| Team | Solo |
| Repo | {repo_url} |
| Live demo / site | {site_url} |
| LinkedIn post (nominate) | <paste the launch post URL> |
| X post (nominate) | <paste the URL of tweet 1 of the thread> |
| Data | All callers, names and identifiers are synthetic; the only cloned voice is my own, with recorded consent. |
"""
    paths = []
    for name, body in (("LINKEDIN_POST.md", post), ("FIRST_COMMENT.md", first_comment), ("X_THREAD.md", x_thread),
                       ("COMMENT_REPLIES.md", replies), ("FOLLOW_UPS.md", followups),
                       ("TEASER.md", teaser), ("SUBMISSION.md", submission)):
        p = kit_dir / name
        p.write_text(body, encoding="utf-8")
        paths.append(p)
    return paths


def copy_reels_to_kit(reels: dict[str, dict[str, Path]], kit_dir: Path) -> None:
    d = kit_dir / "reels"
    d.mkdir(parents=True, exist_ok=True)
    for name, by_aspect in reels.items():
        for aspect, p in by_aspect.items():
            if p and Path(p).exists():
                shutil.copy2(p, d / f"{name}_{aspect.replace(':', 'x')}.mp4")
