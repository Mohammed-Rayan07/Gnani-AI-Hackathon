"""Judge a run: deterministic checks first, then the LLM rubric, then aggregation.

The bot is judged on what it ACTUALLY said whenever it exposes its reply text
(our reference bot does). The heard transcript is judged too: a failure that
appears only in the heard view is a HARNESS error (our STT misheard the bot
through the line), reported in the harness-noise table, never blamed on the bot.
Noise that makes the BOT mishear the caller is the bot's problem, as in real life.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from ..models import CallRecord, CallVerdict, CriterionResult, Persona, Scenario
from ..orchestrator import load_calls
from . import deterministic, rubric
from .stats import cer, wilson


def _passed(criteria: list[CriterionResult]) -> bool:
    return all(c.status in ("pass", "na") for c in criteria)


async def judge_call(call: CallRecord, p: Persona, sc: Scenario, judge_llm, use_llm: bool) -> tuple[CallVerdict, dict]:
    has_true = any(t.bot_text_true for t in call.turns)
    views = {}
    for view in (["true", "heard"] if has_true else ["heard"]):
        crit = deterministic.run_all(call, p, sc, view)
        if use_llm:
            crit += await rubric.judge_call(judge_llm, call, p, sc, view)
        views[view] = crit
    primary = views["true" if has_true else "heard"]
    passed = _passed(primary)
    if passed and has_true and not _passed(views["heard"]):
        kind = "harness"                       # only the noisy-heard view failed
    elif passed:
        kind = "none"
    elif any(c.status == "fail" for c in primary):
        kind = "bot"
    else:
        kind = "review"                        # only unverified judge verdicts: needs a human
    v = CallVerdict(
        call_id=call.call_id, persona_id=call.persona_id, scenario_id=call.scenario_id, seed=call.seed,
        bot_version=call.bot_version, passed=passed, criteria=primary, failure_kind=kind,  # type: ignore[arg-type]
        judge_model=getattr(judge_llm, "label", "") if use_llm else "deterministic only",
    )
    extra = {"view": "true" if has_true else "heard",
             "heard_view": [c.model_dump() for c in views["heard"]] if has_true else None}
    return v, extra


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 2)


def summarize(calls: list[CallRecord], verdicts: list[CallVerdict]) -> dict:
    by_cell: dict[tuple[str, str], list[CallVerdict]] = defaultdict(list)
    for v in verdicts:
        by_cell[(v.persona_id, v.scenario_id)].append(v)
    cells = []
    for (pid, sid), vs in sorted(by_cell.items()):
        n, k = len(vs), sum(v.passed for v in vs)
        need = math.ceil(2 * n / 3)
        fails = defaultdict(int)
        for v in vs:
            for c in v.criteria:
                if c.status == "fail":
                    fails[c.name] += 1
        cells.append({"persona": pid, "scenario": sid, "seeds": n, "passed_seeds": k,
                      "cell_pass": k >= need, "rule": f">= {need}/{n} seeds", "failing_criteria": dict(fails),
                      "calls": [v.call_id for v in vs]})
    n_calls = len(verdicts)
    n_pass = sum(v.passed for v in verdicts)
    crit_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for v in verdicts:
        for c in v.criteria:
            crit_counts[c.name][c.status] += 1

    lat, gaps = [], []
    noise: dict[str, list[float]] = defaultdict(list)
    for call in calls:
        for t in call.turns[1:]:
            tm = t.timing
            if tm.response_latency_s is not None:
                lat.append((tm.response_latency_s or 0) + (tm.leading_silence_s or 0))
            if tm.max_internal_gap_s is not None:
                gaps.append(tm.max_internal_gap_s)
        for t in call.turns:
            if t.bot_text_true and t.bot_text_heard is not None:
                c = cer(t.bot_text_true, t.bot_text_heard)
                if c is not None:
                    noise[call.channel].append(c)

    return {
        "calls": n_calls,
        "calls_passed": n_pass,
        "call_pass_rate": round(n_pass / n_calls, 3) if n_calls else None,
        "call_pass_ci95": [round(x, 3) for x in wilson(n_pass, n_calls)],
        "cells": cells,
        "cells_passed": sum(c["cell_pass"] for c in cells),
        "cells_total": len(cells),
        "criteria": {k: dict(v) for k, v in crit_counts.items()},
        "failure_kinds": {k: sum(v.failure_kind == k for v in verdicts) for k in ("bot", "harness", "review")},
        "latency_to_first_word_s": {"p50": pct(lat, 0.5), "p90": pct(lat, 0.9), "n": len(lat)},
        "max_dead_air_s": {"p50": pct(gaps, 0.5), "p90": pct(gaps, 0.9)},
        "harness_noise_cer": {ch: {"mean": round(statistics.mean(v), 3), "median": round(statistics.median(v), 3), "turns": len(v)}
                              for ch, v in sorted(noise.items())},
        "errors": [c.call_id for c in calls if c.ended_by == "error"],
    }


async def judge_run(run_dir: Path, personas: dict, scenarios: dict, judge_llm, use_llm: bool, progress=None) -> dict:
    calls = load_calls(run_dir)
    verdicts, extras = [], {}
    for call in calls:
        v, extra = await judge_call(call, personas[call.persona_id], scenarios[call.scenario_id], judge_llm, use_llm)
        verdicts.append(v)
        extras[call.call_id] = extra
        if progress:
            progress(v)
    summary = summarize(calls, verdicts)
    summary["judge_model"] = verdicts[0].judge_model if verdicts else ""
    (run_dir / "verdicts.json").write_text(
        json.dumps([{**v.model_dump(), **extras[v.call_id]} for v in verdicts], indent=1, ensure_ascii=False), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    return summary
