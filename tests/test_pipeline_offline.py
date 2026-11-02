"""End-to-end dry run: run -> judge -> report -> diff -> reel, all offline."""

import asyncio
import json
import shutil

import pytest

from chakravyuh import models
from chakravyuh.adapters.inprocess import InProcessRefBot
from chakravyuh.clients import build_clients
from chakravyuh.config import get_settings
from chakravyuh.judge import judge_run
from chakravyuh.orchestrator import CallSpec, Orchestrator, write_manifest
from chakravyuh.report import write_diff, write_scorecard


def _run(version, personas=("uncle_traffic", "social_engineer"), scenarios=("kyc_otp_pressure", "balance_block_card")):
    s = get_settings()
    c = build_clients(s)
    bot = InProcessRefBot(version, c.stt, c.tts, c.bot_llm)
    run_dir = s.runs_dir / f"test-{version}"
    write_manifest(run_dir, run_id=f"test-{version}", bot_label=bot.label, bot_version=version, adapter=bot.name,
                   mode=s.mode_label, models={"persona": "x", "stt": "x", "tts": "x"})
    P, S = models.personas(), models.scenarios()
    specs = [CallSpec(P[p], S[sc], seed, P[p].channel) for p in personas for sc in scenarios for seed in (1, 2)]
    recs = asyncio.run(Orchestrator(c, bot, run_dir, f"test-{version}").run_matrix(specs, 4))
    summary = asyncio.run(judge_run(run_dir, P, S, c.judge_llm, use_llm=False))
    return run_dir, recs, summary


def test_full_pipeline_offline():
    a, recs_a, sa = _run("v1")
    b, recs_b, sb = _run("v2")
    assert all(r.ended_by != "error" for r in recs_a + recs_b)
    assert all((a / "calls" / r.call_id / "t01_caller_line.wav").exists() for r in recs_a)
    # v1 reads the fake account number to the KYC caller; v2 must not
    va = {v["call_id"]: v for v in json.loads((a / "verdicts.json").read_text())}
    vb = {v["call_id"]: v for v in json.loads((b / "verdicts.json").read_text())}
    leak = lambda v: next(c for c in v["criteria"] if c["name"] == "pii_leak")["status"]
    kyc_a = [v for k, v in va.items() if "kyc_otp_pressure" in k]
    kyc_b = [v for k, v in vb.items() if "kyc_otp_pressure" in k]
    assert all(leak(v) == "fail" for v in kyc_a)
    assert all(leak(v) == "pass" for v in kyc_b)
    assert sb["calls_passed"] >= sa["calls_passed"]
    assert write_scorecard(a).exists() and write_diff(a, b).exists()
    html = (a / "scorecard.html").read_text()
    assert "OFFLINE DRY RUN" in html


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_reel_renders():
    from chakravyuh.reel import render_reel
    a, recs, _ = _run("v1", personas=("social_engineer",), scenarios=("kyc_otp_pressure",))
    p = render_reel(a, recs[0].call_id, max_seconds=8)
    assert p.exists() and p.stat().st_size > 10_000
