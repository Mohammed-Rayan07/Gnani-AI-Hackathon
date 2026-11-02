"""Content-addressed disk cache. A cache hit costs zero credits."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def key(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, (bytes, bytearray)):
            h.update(bytes(p))
        else:
            h.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


class DiskCache:
    def __init__(self, root: Path, namespace: str):
        self.dir = Path(root) / namespace
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, k: str, ext: str) -> Path:
        return self.dir / k[:2] / f"{k}.{ext}"

    def get_bytes(self, k: str, ext: str = "bin") -> bytes | None:
        p = self._path(k, ext)
        return p.read_bytes() if p.exists() else None

    def put_bytes(self, k: str, data: bytes, ext: str = "bin") -> None:
        p = self._path(k, ext)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get_json(self, k: str):
        b = self.get_bytes(k, "json")
        return json.loads(b) if b is not None else None

    def put_json(self, k: str, obj) -> None:
        self.put_bytes(k, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "json")
