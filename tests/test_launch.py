"""Offline `chakravyuh launch`: every artefact is produced, resumes cleanly, and dry-run numbers never reach README."""

import hashlib
import json
import shutil

import pytest
from typer.testing import CliRunner

from chakravyuh.cli import app
from chakravyuh.config import ROOT

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_offline_launch_end_to_end(tmp_path):
    readme_before = _sha(ROOT / "README.md")
    results_md = ROOT / "docs" / "RESULTS.md"
    results_before = _sha(results_md) if results_md.exists() else None
    site, kit = tmp_path / "site", tmp_path / "launch"
    args = ["launch", "--personas", "social_engineer,uncle_traffic", "--seeds", "1", "--max-turns", "4",
            "--steps", "run,judge,reels,site,results,kit,video", "--site-dir", str(site), "--kit-dir", str(kit)]
    r = CliRunner().invoke(app, args)
    assert r.exit_code == 0, r.output

    runs = tmp_path / "runs"
    for v in ("v1", "v2"):
        assert (runs / f"launch-{v}" / "summary.json").exists()
        assert (runs / f"launch-{v}" / "scorecard.html").exists()
    assert (site / "index.html").exists() and (site / "diff.html").exists()
    assert (kit / "LINKEDIN_POST.md").read_text().startswith("<!-- OFFLINE DRY RUN NUMBERS: DO NOT POST -->")
    assert (kit / "RESULTS.offline.md").exists()
    assert (kit / "reels").glob("leak_*.mp4")
    for aspect in ("4x5", "16x9"):
        assert (kit / f"demo_{aspect}.mp4").stat().st_size > 50_000

    # numbers in the post are the judged numbers
    s1 = json.loads((runs / "launch-v1" / "summary.json").read_text())
    calls = s1["calls"] + json.loads((runs / "launch-v2" / "summary.json").read_text())["calls"]
    assert f"I made {calls} phone calls" in (kit / "LINKEDIN_POST.md").read_text()

    # offline never touches the public docs
    assert _sha(ROOT / "README.md") == readme_before
    assert (_sha(results_md) if results_md.exists() else None) == results_before

    # resume: a second run skips every finished call
    r2 = CliRunner().invoke(app, args[:-6] + ["--steps", "run", "--site-dir", str(site), "--kit-dir", str(kit)])
    assert r2.exit_code == 0 and "running 0" in r2.output


def test_results_table_and_readme_markers(tmp_path):
    from chakravyuh import launch as L
    f = {"v1_cells": 1, "v2_cells": 5, "cells_total": 6, "v1_rate": 0.2, "v2_rate": 0.8, "v1_ci": [0.1, 0.4],
         "v2_ci": [0.6, 0.9], "v1_leaks": 4, "v2_leaks": 0, "v1_latency": {"p50": 1.2, "p90": 2.5},
         "v2_latency": {"p50": 1.0, "p90": 2.0}, "human_kappa": {}, "evon_agreement": {}, "offline": False}
    table = L.results_table(f)
    assert "| Scenarios passed (≥2/3 seeds) | 1/6 | 5/6 |" in table and "pending" in table
    readme = tmp_path / "README.md"
    readme.write_text(f"x\n{L.README_START}\nold\n{L.README_END}\ny\n")
    assert L.update_readme(f, readme)
    text = readme.read_text()
    assert "old" not in text and "| Calls leaking a fake identifier | 4 | 0 |" in text and text.endswith("y\n")
