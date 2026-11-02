"""Credit ledger with a hard cap.

Every billable Gnani call reserves its estimated cost *before* the request.
If the cap would be exceeded the call is refused. A failed request is refunded.
Rates are third-party estimates until you confirm them on the usage page
(set RATE_* in .env after your first STT and TTS calls).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Rates:
    stt_per_min: float
    tts_per_1k_chars: float
    vc_per_call: float

    def stt(self, seconds: float) -> float:
        return self.stt_per_min * seconds / 60.0

    def tts(self, chars: int) -> float:
        return self.tts_per_1k_chars * chars / 1000.0


class Ledger:
    def __init__(self, path: Path, cap: float, rates: Rates):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cap = cap
        self.rates = rates
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS entries ("
                "id INTEGER PRIMARY KEY, ts REAL, kind TEXT, units REAL, cost REAL, status TEXT, meta TEXT)"
            )

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def spent(self) -> float:
        with self._conn() as c:
            (v,) = c.execute("SELECT COALESCE(SUM(cost),0) FROM entries WHERE status!='refunded'").fetchone()
        return float(v)

    def remaining(self) -> float:
        return self.cap - self.spent()

    def summary(self) -> dict:
        with self._conn() as c:
            rows = c.execute(
                "SELECT kind, COUNT(*), SUM(units), SUM(cost) FROM entries WHERE status!='refunded' GROUP BY kind"
            ).fetchall()
        return {
            "cap": self.cap,
            "spent": round(self.spent(), 2),
            "by_kind": {k: {"calls": n, "units": round(u or 0, 2), "cost": round(cst or 0, 2)} for k, n, u, cst in rows},
        }

    @contextmanager
    def reserve(self, kind: str, units: float, cost: float, meta: str = ""):
        with self._lock:
            if self.spent() + cost > self.cap:
                raise BudgetExceeded(
                    f"{kind}: cost {cost:.2f} would exceed cap {self.cap:.0f} (spent {self.spent():.2f}). "
                    "Raise CREDIT_CAP deliberately if you mean it."
                )
            with self._conn() as c:
                cur = c.execute(
                    "INSERT INTO entries(ts, kind, units, cost, status, meta) VALUES (?,?,?,?,?,?)",
                    (time.time(), kind, units, cost, "reserved", meta[:200]),
                )
                row_id = cur.lastrowid
        try:
            yield
        except BaseException:
            with self._conn() as c:
                c.execute("UPDATE entries SET status='refunded' WHERE id=?", (row_id,))
            raise
        else:
            with self._conn() as c:
                c.execute("UPDATE entries SET status='ok' WHERE id=?", (row_id,))
