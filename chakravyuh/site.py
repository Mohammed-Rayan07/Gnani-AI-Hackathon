"""Static 'Hear it fail' site: index + per-run scorecards + v1->v2 diff, with only the audio they reference."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .report import TEMPLATES, write_diff, write_scorecard

AUDIO_RE = re.compile(r'src="(calls/[^"]+\.wav)"')
REEL_GLOB = "reels/*.mp4"


def _copy_run(run_dir: Path, dest: Path) -> dict:
    """Copy one judged run's scorecard + only the referenced audio + reels; return its card info."""
    sc = write_scorecard(run_dir)
    dest.mkdir(parents=True, exist_ok=True)
    html = sc.read_text(encoding="utf-8")
    for rel in sorted(set(AUDIO_RE.findall(html))):
        src = run_dir / rel
        if src.exists():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    (dest / "index.html").write_text(html, encoding="utf-8")
    reels = []
    for r in sorted(run_dir.glob(REEL_GLOB)):
        (dest / "reels").mkdir(exist_ok=True)
        shutil.copy2(r, dest / "reels" / r.name)
        reels.append(f"reels/{r.name}")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return {"dir": dest.name, "manifest": manifest, "summary": summary, "reels": reels}


def _built_on(runs: list[Path]) -> str:
    """Name only the Gnani models these runs actually used (never claim Evon or cloning that did not run)."""
    cloned = evon = False
    for r in map(Path, runs):
        evon |= (r / "summary.evon.json").exists()
        for call in r.glob("calls/*/call.json"):
            if "cloned" in call.read_text(encoding="utf-8"):
                cloned = True
                break
    parts = ["Gnani Prisma", "Timbre" + (" (plus voice cloning)" if cloned else "")]
    if evon:
        parts.append("Evon")
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def build_site(runs: list[Path], out: Path) -> Path:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cards = [_copy_run(Path(r), out / Path(r).name) for r in runs]
    diff_rel = None
    main = [r for r in runs if not Path(r).name.startswith("caller-")]
    if len(main) >= 2:
        a, b = Path(main[0]), Path(main[1])
        # diff failures are a subset of each run's scorecard failures, whose audio is already copied
        d = write_diff(a, b, out / "diff.html", link_a=f"{a.name}/", link_b=f"{b.name}/")
        diff_rel = d.name
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["pct"] = lambda x: "-" if x is None else f"{x * 100:.0f}%"
    html = env.get_template("site_index.html.j2").render(cards=cards, diff=diff_rel, built_on=_built_on(runs),
                                                         offline=any("OFFLINE" in c["manifest"].get("mode", "") for c in cards))
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return out / "index.html"
