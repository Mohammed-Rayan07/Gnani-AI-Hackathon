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
    "call_completed": "Completed", "bot_repetition": "Repeats itself", "task_success": "Task", "hallucination": "Hallucination",
    "policy_adherence": "Policy", "recovery": "Recovery", "social_engineering_resistance": "Social-eng.",
}


NICE = {"kyc_otp_pressure": "KYC + OTP pressure", "balance_block_card": "Balance + block card",
        "emi_double_debit": "EMI double debit", "uncle_traffic": "Uncle in traffic", "tamil_aunty": "Tamil aunty",
        "farmer_2g": "Farmer on 2G", "social_engineer": "Social engineer", "kannada_auto": "Kannada auto driver",
        "city_4g": "City 4G", "rural_2g": "Rural 2G", "clean_pstn": "Clean landline"}
_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">')
_PATHS = {
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "alert": '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "phone": '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/>',
    "head": '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>',
    "chev": '<path d="m9 18 6-6-6-6"/>',
    "arrow": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "wave": '<path d="M2 12h2M6 8v8M10 5v14M14 9v6M18 7v10M22 12h-2"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "bot": '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M12 8V4M8 14h.01M16 14h.01"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "mic": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5"/>',
    "scale": '<path d="M12 3v18M5 21h14M7 7h10M7 7l-3 7a3 3 0 0 0 6 0zM17 7l-3 7a3 3 0 0 0 6 0z"/>',
}
ICON = {k: _SVG + v + "</svg>" for k, v in _PATHS.items()}


def nice(x) -> str:
    x = str(x)
    return NICE.get(x, x.replace("_", " ").capitalize())


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["pct"] = lambda x: "-" if x is None else f"{x * 100:.0f}%"
    env.filters["nice"] = nice
    env.globals.update(CRIT=CRITERION_LABELS, ICON=ICON, root=None, nav_diff=False, page="",
                       repo_url=os.environ.get("CHAKRAVYUH_REPO_URL", "https://github.com/Mohammed-Rayan07/Gnani-AI-Hackathon"))
    return env


def _leaks(verdicts: list[dict]) -> int:
    return sum(1 for v in verdicts for c in v["criteria"] if c["name"] == "pii_leak" and c["status"] == "fail")


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
    out = Path(run_dir) / "scorecard.html"
    out.write_text(render_scorecard(run_dir), encoding="utf-8")
    return out


def render_scorecard(run_dir: Path, root: str | None = None, nav_diff: bool = False) -> str:
    """root: relative path to the site root when the page is part of a site (adds the top navigation)."""
    run_dir = Path(run_dir)
    manifest, summary, verdicts, calls = _load(run_dir)
    personas = sorted({c["persona"] for c in summary["cells"]})
    scenarios = sorted({c["scenario"] for c in summary["cells"]})
    grid = {(c["persona"], c["scenario"]): c for c in summary["cells"]}
    leaks = _leaks(verdicts)
    return _env().get_template("scorecard.html.j2").render(root=root, nav_diff=nav_diff, page="scorecard",
        m=manifest, s=summary, personas=personas, scenarios=scenarios, grid=grid, leaks=leaks,
        failures=_failure_rows(verdicts, calls), calls=calls, verdicts=verdicts,
        profiles={p["name"]: p for p in channel.profile_table()},
        offline="OFFLINE" in manifest.get("mode", ""),
    )


def write_diff(run_a: Path, run_b: Path, out: Path | None = None, link_a: str | None = None, link_b: str | None = None,
               root: str | None = None) -> Path:
    """link_a/link_b: audio URL prefixes to use instead of paths relative to the run folders (site builds)."""
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
    rel_a = link_a if link_a is not None else os.path.relpath(run_a, out.parent).replace(os.sep, "/") + "/"
    rel_b = link_b if link_b is not None else os.path.relpath(run_b, out.parent).replace(os.sep, "/") + "/"
    still_failing = [r for r in _failure_rows(vb, cb, rel_b) if r["v"]["failure_kind"] == "bot"]
    html = _env().get_template("diff.html.j2").render(
        root=root, nav_diff=root is not None, page="diff", leaks_a=_leaks(va), leaks_b=_leaks(vb), ma=ma, mb=mb, sa=sa, sb=sb, ga=ga, gb=gb, keys=keys, ci_a=ci_a, ci_b=ci_b, verdict=verdict,
        fixed=[r for r in _failure_rows(va, ca, rel_a) if r["v"]["failure_kind"] == "bot"
               and gb.get((r["v"]["persona_id"], r["v"]["scenario_id"]), {}).get("cell_pass")],
        still_failing=still_failing,
        offline="OFFLINE" in ma.get("mode", "") or "OFFLINE" in mb.get("mode", ""),
    )
    out.write_text(html, encoding="utf-8")
    return out
