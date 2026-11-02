"""Hand labels vs the judge: the "how much should you trust the LLM judge" number."""

from __future__ import annotations

import json
from pathlib import Path

from ..orchestrator import load_calls
from .stats import cohens_kappa


def _labels_path(run_dir: Path) -> Path:
    return Path(run_dir) / "labels.jsonl"


def load_labels(run_dir: Path) -> dict[str, bool]:
    p = _labels_path(run_dir)
    out = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["call_id"]] = bool(d["human_pass"])
    return out


def interactive_label(run_dir: Path, limit: int) -> None:
    """Label blind: the judge's verdict is NOT shown, to avoid anchoring."""
    run_dir = Path(run_dir)
    done = load_labels(run_dir)
    calls = [c for c in load_calls(run_dir) if c.call_id not in done]
    print(f"{len(done)} already labelled. Labelling up to {limit - len(done)} more. Answer p(ass) / f(ail) / s(kip) / q(uit).")
    with _labels_path(run_dir).open("a", encoding="utf-8") as fh:
        for call in calls[: max(0, limit - len(done))]:
            print("\n" + "=" * 80 + f"\n{call.call_id}  (audio: {run_dir / 'calls' / call.call_id})")
            for t in call.turns:
                if t.caller_text:
                    print(f"  CALLER: {t.caller_text}")
                print(f"  BOT:    {t.bot_text_true or t.bot_text_heard}")
            ans = input("Did the BOT handle this call acceptably? [p/f/s/q] ").strip().lower()
            if ans.startswith("q"):
                break
            if ans[:1] in ("p", "f"):
                fh.write(json.dumps({"call_id": call.call_id, "human_pass": ans.startswith("p")}) + "\n")
                fh.flush()


def kappa_report(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    labels = load_labels(run_dir)
    verdicts = {v["call_id"]: v for v in json.loads((run_dir / "verdicts.json").read_text(encoding="utf-8"))}
    pairs = [(verdicts[cid]["passed"], h) for cid, h in labels.items() if cid in verdicts]
    disagreements = [cid for cid, h in labels.items() if cid in verdicts and verdicts[cid]["passed"] != h]
    k = cohens_kappa(pairs)
    rep = {"labelled": len(pairs), "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 3) if pairs else None,
           "cohens_kappa": None if k is None else round(k, 3), "disagreements": disagreements,
           "judge_model": next(iter(verdicts.values()))["judge_model"] if verdicts else None}
    (run_dir / "kappa.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep
