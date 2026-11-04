"""chakravyuh: crash-test dummies for Indian voice bots.

  chakravyuh smoke                         # day-1: TTS -> line -> STT round trip on every profile
  chakravyuh clone-voice me.wav --name me  # your own voice only (docs/CONSENT.md)
  chakravyuh run --bot inprocess:v1        # run the matrix against the reference bot
  chakravyuh judge runs/<id>
  chakravyuh report runs/<id>
  chakravyuh diff runs/<v1> runs/<v2>
  chakravyuh caller "my nani who mixes Bhojpuri and Hindi"
  chakravyuh reel runs/<id> <call_id>
  chakravyuh label runs/<id>  /  chakravyuh kappa runs/<id>
  chakravyuh budget
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import typer

from .clients import Clients, build_clients, build_ledger
from .config import ROOT as ROOT_DIR
from .config import get_settings
from .orchestrator import estimate_cost

# Windows consoles default to cp1252, which crashes on Devanagari/Tamil transcripts and "→".
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure") and (getattr(_stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
        _stream.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def _out(msg: str = "") -> None:
    typer.echo(msg)


def _usage_line(c: Clients) -> str:
    parts = []
    for role, x in (("persona", c.persona_llm), ("bot", c.bot_llm), ("judge", c.judge_llm)):
        u = getattr(x, "usage", None)
        if u and u["requests"]:
            parts.append(f"{role} {getattr(x, 'label', '?')}: {u['requests']} req, "
                         f"{u['prompt_tokens'] + u['completion_tokens']:,} tokens")
    return "LLM usage: " + ("; ".join(parts) if parts else "none")


async def _close(c: Clients) -> None:
    for x in (c.stt, c.tts, c.persona_llm, c.bot_llm, c.judge_llm):
        if hasattr(x, "aclose"):
            await x.aclose()


def _make_bot(spec: str, c: Clients):
    kind, _, rest = spec.partition(":")
    if kind == "inprocess":
        from .adapters.inprocess import InProcessRefBot
        return InProcessRefBot(rest or "v1", c.stt, c.tts, c.bot_llm)
    if kind == "audio-http":
        from .adapters.http import AudioHTTPBot
        return AudioHTTPBot(rest, version=rest.rstrip("/").rsplit("/", 1)[-1])
    if kind == "text-http":
        from .adapters.http import TextHTTPBot
        return TextHTTPBot(rest, c.stt, c.tts, version=rest.rstrip("/").rsplit("/", 1)[-1])
    raise typer.BadParameter("--bot must be inprocess:v1|v2, audio-http:<url>, or text-http:<url>")


def _check_judge_differs(c: Clients, allow_same: bool) -> None:
    j, b = c.settings.judge_llm, c.settings.bot_llm
    if j.configured and b.configured and j.model == b.model and j.base_url == b.base_url and not allow_same:
        raise typer.BadParameter("JUDGE_LLM must differ from BOT_LLM (a model grading itself is not a test). "
                                 "Pass --allow-same-judge only for debugging.")


# ----------------------------------------------------------------------------- doctor

@app.command()
def doctor(offline_ok: bool = typer.Option(False, help="only check config, make no API calls")):
    """Verify .env, keys, network, Gnani TTS/STT (8 kHz too) and all three LLMs. Prints fixes."""
    from . import doctor as d

    s = get_settings()
    checks = d.config_checks(s)

    async def go():
        if offline_ok or s.offline or not s.gnani_api_key:
            return []
        c = build_clients(s)
        res = await d.network_checks(s)
        res += await d.gnani_checks(s, c)
        res += await d.llm_checks(s, c)
        _out(f"\nCredits used by doctor: {c.ledger.summary()['spent']}")
        await _close(c)
        return res

    checks += asyncio.run(go())
    _out("")
    for ch in checks:
        _out(f"  {'OK  ' if ch.ok else 'FAIL'}  {ch.name:<30} {ch.detail}")
        if not ch.ok and ch.fix:
            _out(f"        fix: {ch.fix}")
    bad = [ch for ch in checks if not ch.ok]
    _out(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed." + ("" if bad else " Ready: run `chakravyuh smoke` next."))
    if bad:
        raise typer.Exit(code=1)


# ----------------------------------------------------------------------------- smoke

@app.command()
def smoke(text: str = typer.Option("मेरा balance बताइए, और card block करना है, ending चार चार एक सात।", help="line to synthesize"),
          voice: str = typer.Option("Deepak"), language: str = typer.Option("hi-IN")):
    """Day-1 check: one Timbre line through every channel profile, transcribed by Prisma."""
    from . import audio, channel
    from .judge.stats import cer, phonetic_cer

    s = get_settings()
    c = build_clients(s)
    out_dir = s.runs_dir / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    async def go():
        x, sr = await c.tts.synthesize(text, voice=voice, language=language)
        audio.write_wav(out_dir / "clean.wav", x, sr)
        _out(f"[{s.mode_label}] TTS {voice}/{language}: {len(x) / sr:.1f}s @ {sr} Hz -> {out_dir / 'clean.wav'}")
        clean = await c.stt.transcribe(x, sr, reference_text=text)
        _out(f"  clean 16k   CER {cer(text, clean.text) or 0:.2f} phonetic {phonetic_cer(text, clean.text) or 0:.2f} lang={clean.detected_language}  {clean.text}")
        for name in channel.PROFILES:
            r = channel.degrade(x, sr, name, seed=1)
            audio.write_wav(out_dir / f"{name}.wav", r.audio, r.sr)
            res = await c.stt.transcribe(r.audio, r.sr, reference_text=text)
            _out(f"  {name:<11} CER {cer(text, res.text) or 0:.2f} phonetic {phonetic_cer(text, res.text) or 0:.2f} lang={res.detected_language} loss={r.meta['measured_loss']:.0%} codec={r.meta['codec']}  {res.text}")
        _out(f"Credits used so far: {c.ledger.summary()}")
        _out("Listen to the wavs, then put real per-unit rates from the usage page into .env (RATE_*).")
        await _close(c)

    asyncio.run(go())


@app.command("clone-voice")
def clone_voice(wav: Path, name: str = typer.Option("me"), i_consent: bool = typer.Option(False, "--i-consent", help="confirm this is YOUR voice")):
    """Create a Timbre speaker embedding from 5-30 s of YOUR OWN clean speech."""
    if not i_consent:
        raise typer.BadParameter("Clone only your own voice. Re-run with --i-consent and record it in docs/CONSENT.md.")
    s = get_settings()
    c = build_clients(s)

    async def go():
        p = await c.tts.create_embedding(wav, name)
        _out(f"Saved {p} (gitignored). Personas with voice 'clone:{name}' will now use it.")
        await _close(c)

    asyncio.run(go())


# ----------------------------------------------------------------------------- run

@app.command()
def run(bot: str = typer.Option("inprocess:v1", help="inprocess:v1|v2, audio-http:<url>, text-http:<url>"),
        personas: str = typer.Option("uncle_traffic,tamil_aunty,farmer_2g,social_engineer", help="comma list or 'all'"),
        scenarios: str = typer.Option("all", help="comma list or 'all'"),
        seeds: int = typer.Option(3), channel_override: str = typer.Option("", "--channel", help="force one profile for every persona"),
        max_turns: int = typer.Option(0, help="override every scenario's max caller turns (0 = scenario default)"),
        concurrency: int = typer.Option(0, help="0 = CONCURRENCY from .env"),
        yes: bool = typer.Option(False, "--yes", help="skip the cost confirmation"),
        tag: str = typer.Option("", help="label stored in the manifest")):
    """Run personas x scenarios x seeds against a bot."""
    from . import models
    from .orchestrator import CallSpec, Orchestrator, estimate_cost, new_run_id, write_manifest

    s = get_settings()
    c = build_clients(s)
    all_p, all_s = models.personas(), models.scenarios()
    pids = list(all_p) if personas == "all" else [x.strip() for x in personas.split(",") if x.strip()]
    sids = list(all_s) if scenarios == "all" else [x.strip() for x in scenarios.split(",") if x.strip()]
    for pid in pids:
        if pid not in all_p:
            raise typer.BadParameter(f"unknown persona {pid}; have {list(all_p)}")
    for sid in sids:
        if sid not in all_s:
            raise typer.BadParameter(f"unknown scenario {sid}; have {list(all_s)}")
    bot_obj = _make_bot(bot, c)
    ours = bot.startswith("inprocess")
    specs = []
    for pid in pids:
        p = all_p[pid]
        if p.adversarial and not ours:
            _out(f"skip {pid}: adversarial personas only run against your own bot (see docs/CONSENT.md)")
            continue
        for sid in sids:
            for seed in range(1, seeds + 1):
                sc = all_s[sid].model_copy(update={"max_turns": max_turns}) if max_turns else all_s[sid]
                specs.append(CallSpec(p, sc, seed, channel_override or p.channel))
    est = estimate_cost(c, specs, ours)
    _out(f"[{s.mode_label}] {len(specs)} calls against {bot_obj.label}. Estimated cost <= {est:.0f} credits "
         f"(remaining budget {c.ledger.remaining():.0f}).")
    if not s.offline and est > s.confirm_above and not yes:
        raise typer.Exit(code=_abort(f"Estimated {est:.0f} > CONFIRM_ABOVE={s.confirm_above:.0f}. Re-run with --yes."))
    run_id = new_run_id(bot_obj.version)
    run_dir = s.runs_dir / run_id
    write_manifest(run_dir, run_id=run_id, bot=bot, bot_label=bot_obj.label, bot_version=bot_obj.version,
                   adapter=bot_obj.name, mode=s.mode_label, personas=pids, scenarios=sids, seeds=seeds,
                   channel_override=channel_override, max_turns=max_turns or "scenario default", tag=tag, estimate=est,
                   models={"persona": c.persona_llm.label, "bot": c.bot_llm.label, "judge": c.judge_llm.label,
                           "stt": getattr(c.stt, "label", "?"), "tts": "offline-tts" if s.offline else s.tts_model})
    orch = Orchestrator(c, bot_obj, run_dir, run_id)
    done = [0]

    def tick(rec):
        done[0] += 1
        status = "ERROR " + (rec.error or "") if rec.ended_by == "error" else f"{len(rec.turns) - 1} turns, ended by {rec.ended_by}"
        _out(f"  [{done[0]}/{len(specs)}] {rec.call_id}: {status}")

    async def go():
        await orch.run_matrix(specs, concurrency or s.concurrency, on_done=tick)
        await _close(c)

    asyncio.run(go())
    _out(f"Run saved to {run_dir}\nSpent so far: {c.ledger.summary()['spent']} credits\n{_usage_line(c)}\nNext: chakravyuh judge {run_dir}")


def _abort(msg: str) -> int:
    typer.echo(msg, err=True)
    return 2


# ----------------------------------------------------------------------------- judge / report

@app.command()
def judge(run_dir: Path, no_llm: bool = typer.Option(False, "--no-llm", help="deterministic checks only"),
          allow_same_judge: bool = typer.Option(False),
          use: str = typer.Option("judge", "--judge", help="'judge' (JUDGE_LLM_*, primary) or 'evon' (EVON_LLM_*, second judge)")):
    """Judge a run (deterministic checks + LLM rubric with verified quotes)."""
    from . import models
    from .clients.llm import LLMClient
    from .judge import judge_run

    s = get_settings()
    c = build_clients(s)
    use_llm = not no_llm and not s.offline
    tag = ""
    if use == "evon":
        if not s.evon_llm.configured:
            raise typer.BadParameter("EVON_LLM_BASE_URL / EVON_LLM_MODEL not set (see docs/EVON_LOCAL.md)")
        c.judge_llm = LLMClient(s.evon_llm)
        tag = "evon"
    elif use != "judge":
        raise typer.BadParameter("--judge must be 'judge' or 'evon'")
    if use_llm:
        if use == "judge" and not s.judge_llm.configured:
            raise typer.BadParameter("JUDGE_LLM_* not configured; use --no-llm for deterministic checks only")
        if use == "judge":
            _check_judge_differs(c, allow_same_judge)

    def tick(v):
        mark = "PASS" if v.passed else f"FAIL[{v.failure_kind}]"
        bad = ", ".join(cr.name for cr in v.criteria if cr.status in ("fail", "unverified"))
        _out(f"  {mark:<14} {v.call_id}  {bad}")

    async def go():
        summ = await judge_run(run_dir, models.personas(), models.scenarios(), c.judge_llm, use_llm, tick, tag=tag)
        await _close(c)
        return summ

    summ = asyncio.run(go())
    _out(_usage_line(c))
    lo, hi = summ["call_pass_ci95"]
    _out(f"\n{summ['calls_passed']}/{summ['calls']} calls passed (95% CI {lo:.0%}-{hi:.0%}); "
         f"{summ['cells_passed']}/{summ['cells_total']} scenarios passed (>= 2/3 seeds). Judge: {summ['judge_model']}")
    _out(f"Failure kinds: {summ['failure_kinds']}   Harness noise CER: {summ['harness_noise_cer']}")
    _out(f"Next: chakravyuh report {run_dir}")


@app.command()
def agree(run_dir: Path, b: str = typer.Option("evon", help="tag of the second judge's verdicts")):
    """Cohen's kappa between the primary judge and a second judge (default: Evon) on the same calls."""
    from .judge import judge_agreement
    _out(json.dumps(judge_agreement(run_dir, "", b), indent=1))


@app.command()
def report(run_dir: Path):
    """Write scorecard.html into the run folder (self-contained, relative audio links)."""
    from .report import write_scorecard
    p = write_scorecard(run_dir)
    _out(f"Scorecard: {p}")


@app.command()
def diff(run_a: Path, run_b: Path, out: Path = typer.Option(None)):
    """Compare two judged runs (e.g. bot v1 vs v2) and write diff.html."""
    from .report import write_diff
    p = write_diff(run_a, run_b, out)
    _out(f"Diff: {p}")


@app.command()
def lint():
    """Fail if any persona/scenario/refbot file contains something that looks like real PII."""
    from .safety import lint_repo_data
    problems = lint_repo_data()
    for p in problems:
        _out("  " + p)
    if problems:
        raise typer.Exit(code=1)
    _out("Synthetic-data lint: clean.")


@app.command()
def site(runs: list[Path], out: Path = typer.Option(Path("site"), help="output folder (publish with GitHub Pages)")):
    """Build the public 'Hear it fail' site from judged runs: give v1 then v2 run folders (plus any caller runs)."""
    from .site import build_site
    p = build_site(runs, out)
    _out(f"Site: {p}  (open index.html locally; push the folder and enable GitHub Pages)")


# ----------------------------------------------------------------------------- launch

REPO_URL = "https://github.com/Mohammed-Rayan07/Gnani-AI-Hackathon"
SITE_URL = "https://mohammed-rayan07.github.io/Gnani-AI-Hackathon/"


@app.command()
def launch(steps: str = typer.Option(",".join(["doctor", "clone", "run", "judge", "reels", "site", "results", "kit", "video", "evon"]),
                                     help="comma list of steps to run, in order"),
           personas: str = typer.Option("uncle_traffic,tamil_aunty,farmer_2g,social_engineer,kannada_auto"),
           seeds: int = typer.Option(3), max_turns: int = typer.Option(6),
           clone: Path = typer.Option(None, help="5-30 s wav of YOUR voice to clone first (needs --i-consent)"),
           i_consent: bool = typer.Option(False, "--i-consent"),
           yes: bool = typer.Option(False, "--yes", help="skip the cost confirmation"),
           site_dir: Path = typer.Option(None, help="default: ./site"), kit_dir: Path = typer.Option(None, help="default: ./launch"),
           publish: bool = typer.Option(False, "--publish", help="git add/commit/push site/, docs/RESULTS.md and README.md at the end")):
    """The whole live pipeline, resumable: re-run the same command after a crash or quota stop."""
    from . import doctor as d
    from . import launch as L
    from .judge import judge_agreement, judge_run

    s = get_settings()
    want = [x.strip() for x in steps.split(",") if x.strip()]
    bad = [x for x in want if x not in L.ALL_STEPS]
    if bad:
        raise typer.BadParameter(f"unknown steps {bad}; valid: {L.ALL_STEPS}")
    cfg = L.LaunchConfig(personas=[x.strip() for x in personas.split(",") if x.strip()], seeds=seeds,
                         max_turns=max_turns, clone_wav=clone, consent=i_consent, steps=want, yes=yes)
    if site_dir:
        cfg.site_dir = site_dir
    if kit_dir:
        cfg.kit_dir = kit_dir
    v1_dir, v2_dir = cfg.run_dir(s, "v1"), cfg.run_dir(s, "v2")
    c = build_clients(s)
    log = _out

    async def go():
        if "doctor" in want and not s.offline:
            log("== doctor")
            checks = d.config_checks(s) + await d.network_checks(s) + await d.gnani_checks(s, c) + await d.llm_checks(s, c)
            failed = [ch for ch in checks if not ch.ok]
            for ch in failed:
                log(f"  FAIL {ch.name}: {ch.detail}\n       fix: {ch.fix}")
            if failed:
                raise typer.Exit(code=_abort("doctor failed; fix the above and re-run (finished steps are kept)"))
            log(f"  {len(checks)}/{len(checks)} OK")
        if "clone" in want and cfg.clone_wav:
            log("== clone")
            if (s.voices_dir / "me.json").exists():
                log("  voices/me.json exists, skipping")
            elif not cfg.consent:
                raise typer.Exit(code=_abort("--clone needs --i-consent (your own voice only; see docs/CONSENT.md)"))
            else:
                log(f"  {await c.tts.create_embedding(cfg.clone_wav, 'me')}")
        if "run" in want:
            log("== run")
            specs = L.build_specs(cfg)
            est = estimate_cost(c, specs, True) * 2
            log(f"  {len(specs)} calls per version x 2 = {2 * len(specs)} calls; estimated <= {est:.0f} credits "
                f"(remaining {c.ledger.remaining():.0f}; finished calls are skipped)")
            if not s.offline and est > s.confirm_above and not cfg.yes:
                raise typer.Exit(code=_abort(f"Re-run with --yes to spend up to {est:.0f} credits."))
            for version, rd in (("v1", v1_dir), ("v2", v2_dir)):
                for attempt in range(cfg.retries + 1):
                    left = await L.run_version(c, version, rd, specs, log)
                    if not left:
                        break
                    log(f"  {version}: {len(left)} calls crashed; retry {attempt + 1}/{cfg.retries} in 60 s")
                    if attempt < cfg.retries:
                        await asyncio.sleep(0 if s.offline else 60)
                if left:
                    log(f"  {version}: {len(left)} calls still crashing (quota?). They are excluded from scoring; "
                        "re-run `chakravyuh launch --steps run,judge,reels,site,results,kit,video` later to finish them.")
            log("  " + _usage_line(c))
        if "judge" in want:
            log("== judge")
            use_llm = not s.offline and s.judge_llm.configured
            if use_llm:
                _check_judge_differs(c, False)
            for rd in (v1_dir, v2_dir):
                summ = await judge_run(rd, models_personas(), models_scenarios(), c.judge_llm, use_llm)
                log(f"  {rd.name}: {summ['cells_passed']}/{summ['cells_total']} scenarios, "
                    f"{summ['calls_passed']}/{summ['calls']} calls passed, errors {len(summ['errors'])}")
            from .report import write_diff, write_scorecard
            for rd in (v1_dir, v2_dir):
                write_scorecard(rd)
            log(f"  diff: {write_diff(v1_dir, v2_dir)}")
        picks, reels = {}, {}
        if any(x in want for x in ("reels", "video", "kit")):
            picks = L.pick_reels(v1_dir, v2_dir)
        if "reels" in want:
            log("== reels")
            reels = L.render_reels(picks, log)
            L.copy_reels_to_kit(reels, cfg.kit_dir)
        else:
            from .reel import SIZES as _RS
            for name, (rd, cid) in picks.items():
                reels[name] = {a: rd / "reels" / f"{cid}_{a.replace(':', 'x')}.mp4" for a in _RS
                               if (rd / "reels" / f"{cid}_{a.replace(':', 'x')}.mp4").exists()}
        if "site" in want:
            log("== site")
            from .site import build_site
            caller_runs = sorted(p for p in s.runs_dir.glob("caller-*") if (p / "summary.json").exists())
            log(f"  {build_site([v1_dir, v2_dir, *caller_runs], cfg.site_dir)}")
        if "evon" in want and s.evon_llm.configured and not s.offline:
            log("== evon (second judge; slow on a laptop, safe to Ctrl+C and resume later)")
            from .clients.llm import LLMClient
            from .cache import DiskCache
            evon = LLMClient(s.evon_llm, DiskCache(s.cache_dir, "llm"))
            for rd in (v1_dir, v2_dir):
                await judge_run(rd, models_personas(), models_scenarios(), evon, True, tag="evon")
                a = judge_agreement(rd, "", "evon")
                log(f"  {rd.name}: agreement {a['agreement']}, kappa {a['kappa']} over {a['calls']} calls")
            await evon.aclose()
        elif "evon" in want:
            log("== evon: EVON_LLM_* not set, skipped (docs/EVON_LOCAL.md)")
        f = None
        if any(x in want for x in ("results", "kit", "video", "evon")):
            f = L.facts(v1_dir, v2_dir)
        if "results" in want or "evon" in want:
            log("== results")
            if s.offline:   # never let dry-run numbers near the public docs
                cfg.kit_dir.mkdir(parents=True, exist_ok=True)
                log(f"  {L.write_results(f, cfg.kit_dir / 'RESULTS.offline.md')} (offline: README untouched)")
            else:
                log(f"  {L.write_results(f, ROOT_DIR / 'docs' / 'RESULTS.md')}")
                log(f"  README results table updated: {L.update_readme(f)}")
        if "kit" in want or "evon" in want:
            log("== kit")
            for p in L.write_kit(f, cfg.kit_dir, REPO_URL, SITE_URL):
                log(f"  {p}")
        if "video" in want:
            log("== video")
            from .video import build_demo
            await build_demo(f, picks, reels, c.tts, s.voices_dir, cfg.kit_dir, v1_dir, repo_url=REPO_URL.replace("https://", ""), log=log)
        await _close(c)

    asyncio.run(go())
    _out(f"\nDone. Launch kit: {cfg.kit_dir}  ·  site: {cfg.site_dir}  ·  results: docs/RESULTS.md\n"
         f"Credits spent so far: {c.ledger.summary()['spent']}")
    if publish:
        if s.offline:
            raise typer.Exit(code=_abort("--publish refused in offline mode (dry-run numbers are never published)"))
        import subprocess
        paths = [p for p in ("site", "docs/RESULTS.md", "README.md") if (ROOT_DIR / p).exists()]
        subprocess.run(["git", "add", "--", *paths], cwd=ROOT_DIR, check=True)
        staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=ROOT_DIR, capture_output=True, text=True).stdout.split()
        leaked = [p for p in staged if p.endswith(".env") or p.startswith(("runs/", "voices/", ".cache/"))]
        if leaked:
            raise typer.Exit(code=_abort(f"refusing to publish private files: {leaked}"))
        if staged:
            subprocess.run(["git", "commit", "-m", "Publish live results, site and README numbers"], cwd=ROOT_DIR, check=True)
            subprocess.run(["git", "push"], cwd=ROOT_DIR, check=True)
            _out(f"Published {len(staged)} files.")
        else:
            _out("Nothing new to publish.")


def models_personas():
    from . import models
    return models.personas()


def models_scenarios():
    from . import models
    return models.scenarios()


@app.command()
def budget():
    """Credits spent so far, by kind."""
    s = get_settings()
    _out(json.dumps(build_ledger(s).summary(), indent=1))


# ----------------------------------------------------------------------------- calibration

@app.command()
def label(run_dir: Path, limit: int = typer.Option(35)):
    """Hand-label calls (pass/fail) so the judge's agreement with you (Cohen's kappa) can be published."""
    from .judge.calibrate import interactive_label
    interactive_label(run_dir, limit)


@app.command()
def kappa(run_dir: Path):
    """Cohen's kappa between the judge and your hand labels."""
    from .judge.calibrate import kappa_report
    _out(json.dumps(kappa_report(run_dir), indent=1))


# ----------------------------------------------------------------------------- comment loop + reels

@app.command()
def caller(description: str, scenario: str = typer.Option("", help="scenario id; default: let the model pick"),
           bot: str = typer.Option("inprocess:v2"), seed: int = typer.Option(1), reel_out: bool = typer.Option(True, "--reel/--no-reel")):
    """Comment loop: turn a free-text caller description into a persona, call the bot, render a reel."""
    from .caller_gen import run_comment_caller
    try:
        asyncio.run(run_comment_caller(description, scenario or None, bot, seed, reel_out, _make_bot, _out))
    except ValueError as e:
        raise typer.Exit(code=_abort(f"Not building this caller: {e}\nSuggested reply: \"I can't use real names, numbers or IDs, but describe the caller without them and I'll build them!\""))


@app.command()
def reel(run_dir: Path, call_id: str, max_seconds: float = typer.Option(15.0), aspect: str = typer.Option("4:5", help="4:5 | 9:16 | 16:9")):
    """Render a captioned crash reel (waveform + transcript + PASS/FAIL stamp) for one call."""
    from .reel import render_reel
    p = render_reel(run_dir, call_id, max_seconds=max_seconds, aspect=aspect)
    _out(f"Reel: {p}")


if __name__ == "__main__":
    sys.exit(app())
