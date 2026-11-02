"""Safety lint: synthetic data only.

- Rejects anything that looks like a real Indian mobile, Aadhaar, PAN, card or
  email in personas, scenarios, comment-loop descriptions and generated text.
- Visibly fake identifiers (FAKE-/TEST prefixes, 00000 mobiles) are allowed.
- A small blocklist (assets/blocklist.txt, one term per line) catches slurs;
  extend it as needed.
"""

from __future__ import annotations

import re
from pathlib import Path

from .config import ROOT

ALLOWED_FAKE = re.compile(r"FAKE[-\w]*|TESTP0000F|00000-?\d{5}|LOAN-FAKE-\d+|BLK-\d{6}|DSP-\d{6}", re.I)
PATTERNS = {
    "indian_mobile": re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"),
    "aadhaar_like": re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)"),
    "pan": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "card_number": re.compile(r"(?<!\d)(?:\d[\s-]?){15,16}(?!\d)"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
}


def _blocklist() -> list[str]:
    p = ROOT / "assets" / "blocklist.txt"
    if not p.exists():
        return []
    return [w.strip().lower() for w in p.read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")]


def find_problems(text: str) -> list[str]:
    scrubbed = ALLOWED_FAKE.sub(" ", text)
    problems = [f"looks like a real {name.replace('_', ' ')}: {m.group(0)!r}"
                for name, pat in PATTERNS.items() for m in pat.finditer(scrubbed)]
    low = text.lower()
    problems += [f"blocked term: {w!r}" for w in _blocklist() if w in low]
    return problems


def lint_file(path: Path) -> list[str]:
    return [f"{path.name}: {p}" for p in find_problems(Path(path).read_text(encoding="utf-8"))]


def lint_repo_data() -> list[str]:
    out = []
    for sub in ("personas", "scenarios", "refbot"):
        for p in sorted((ROOT / sub).glob("*.*")):
            if p.suffix in (".yaml", ".json", ".txt"):
                out += lint_file(p)
    return out
