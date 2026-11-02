"""Static HTML scorecard + v1->v2 diff. Self-contained pages; audio linked relatively."""

from __future__ import annotations

import json
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import channel
from ..judge.stats import separated, wilson
from ..models import CallRecord
from ..orchestrator import load_calls

TEMPLATES = Path(__file__).parent / "templates"
CRITERION_LABELS = {
    "pii_leak": "PII leak", "language_match": "Language", "latency_dead_air": "Dead air",
    "call_completed": "Completed", "task_success": "Task", "hallucination": "Hallucination",
    "policy_adherence": "Policy", "recovery": "Recovery", "social_engineering_resistance": "Social-eng.",
}


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["pct"] = lambda x: "-" if x is None else f"{x * 100:.0f}%"
    env.globals["CRIT"] = CRITERION_LABELS
    return env


def _load(run_dir: Path) -> tuple[dict, dict, list[dict], dict[str, CallRecord]]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    verdicts = json.loads((run_dir / "verdicts.json").read_text(encoding="utf-8"))
    calls = {c.call_id: c for c in load_calls(run_dir)}
    return manifest, summary, verdicts, calls


def _failure_rows(verdicts: list[dict], calls: dict[str, CallRecord], prefix: str = "") -> list[dict]:
    rows = []
    for v in verdicts:
        if v["passed"]:
            continue
        call = calls[v["call_id"]]
        failed = [c for c in v["criteria"] if c["status"] in ("fail", "unverified")]
        turns = {t.index: t for t in call.turns}
        ev_turns = sorted({e.get("turn") for c in failed for e in c.get("evidence", []) if isinstance(e.get("turn"), int)})
        rows.append({
            "v": v, "call": call, "failed": failed, "prefix": f"{prefix}calls/{call.call_id}/",
            "evidence_turns": [turns[i] for i in ev_turns if i in turns][:3],
        })
    rows.sort(key=lambda r: (r["v"]["failure_kind"] != "bot", r["v"]["persona_id"], r["v"]["scenario_id"], r["v"]["seed"]))
    return rows


def write_scorecard(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    manifest, summary, verdicts, calls = _load(run_dir)
    personas = sorted({c["persona"] for c in summary["cells"]})
    scenarios = sorted({c["scenario"] for c in summary["cells"]})
    grid = {(c["persona"], c["scenario"]): c for c in summary["cells"]}
    leaks = sum(1 for v in verdicts for c in v["criteria"] if c["name"] == "pii_leak" and c["status"] == "fail")
    html = _env().get_template("scorecard.html.j2").render(
        m=manifest, s=summary, personas=personas, scenarios=scenarios, grid=grid, leaks=leaks,
        failures=_failure_rows(verdicts, calls), calls=calls, verdicts=verdicts,
        profiles={p["name"]: p for p in channel.profile_table()},
        offline="OFFLINE" in manifest.get("mode", ""),
    )
    out = run_dir / "scorecard.html"
    out.write_text(html, encoding="utf-8")
    return out


def write_diff(run_a: Path, run_b: Path, out: Path | None = None) -> Path:
    run_a, run_b = Path(run_a), Path(run_b)
    ma, sa, va, ca = _load(run_a)
    mb, sb, vb, cb = _load(run_b)
    ga = {(c["persona"], c["scenario"]): c for c in sa["cells"]}
    gb = {(c["persona"], c["scenario"]): c for c in sb["cells"]}
    keys = sorted(set(ga) | set(gb))
    ci_a = wilson(sa["calls_passed"], sa["calls"])
    ci_b = wilson(sb["calls_passed"], sb["calls"])
    if separated(ci_a, ci_b):
        verdict = "improved" if ci_b[0] > ci_a[1] else "regressed"
    else:
        verdict = "inconclusive (95% intervals overlap)"
    out = Path(out) if out else run_b / "diff.html"
    rel_a = os.path.relpath(run_a, out.parent).replace(os.sep, "/") + "/"
    rel_b = os.path.relpath(run_b, out.parent).replace(os.sep, "/") + "/"
    still_failing = [r for r in _failure_rows(vb, cb, rel_b) if r["v"]["failure_kind"] == "bot"]
    html = _env().get_template("diff.html.j2").render(
        ma=ma, mb=mb, sa=sa, sb=sb, ga=ga, gb=gb, keys=keys, ci_a=ci_a, ci_b=ci_b, verdict=verdict,
        fixed=[r for r in _failure_rows(va, ca, rel_a) if r["v"]["failure_kind"] == "bot"
               and gb.get((r["v"]["persona_id"], r["v"]["scenario_id"]), {}).get("cell_pass")],
        still_failing=still_failing,
        offline="OFFLINE" in ma.get("mode", "") or "OFFLINE" in mb.get("mode", ""),
    )
    out.write_text(html, encoding="utf-8")
    return out
