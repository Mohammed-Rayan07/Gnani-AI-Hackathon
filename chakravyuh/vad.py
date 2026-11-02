"""Energy VAD for timing metrics.

Latency and dead air are measured on the bot's *own* output audio, before the
phone line, so the bot is not blamed for noise we injected. That audio is
clean TTS, which is exactly where a simple adaptive-energy VAD is reliable
(no Silero/onnx dependency needed). Prisma returns no word timestamps, so this
is the only timing source.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FRAME_MS = 20


@dataclass
class Timing:
    leading_silence_s: float
    trailing_silence_s: float
    speech_s: float
    max_internal_gap_s: float
    segments: list[tuple[float, float]]


def speech_mask(x: np.ndarray, sr: int, rel_db: float = -35.0, abs_floor: float = 1e-4) -> np.ndarray:
    frame = int(sr * FRAME_MS / 1000)
    n = len(x) // frame
    if n == 0:
        return np.zeros(0, dtype=bool)
    e = np.sqrt(np.mean(x[: n * frame].reshape(n, frame).astype(np.float64) ** 2, axis=1))
    thresh = max(e.max() * 10 ** (rel_db / 20), abs_floor)
    m = e > thresh
    # hangover: bridge gaps under 200 ms (stop consonants, breaths)
    bridge = int(200 / FRAME_MS)
    idx = np.flatnonzero(m)
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= bridge:
            m[a:b] = True
    return m


def segments(x: np.ndarray, sr: int) -> list[tuple[float, float]]:
    m = speech_mask(x, sr)
    out, start = [], None
    for i, v in enumerate(m):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start * FRAME_MS / 1000, i * FRAME_MS / 1000))
            start = None
    if start is not None:
        out.append((start * FRAME_MS / 1000, len(m) * FRAME_MS / 1000))
    return out


def timing(x: np.ndarray, sr: int) -> Timing:
    dur = len(x) / sr
    segs = segments(x, sr)
    if not segs:
        return Timing(dur, 0.0, 0.0, 0.0, [])
    gaps = [b[0] - a[1] for a, b in zip(segs[:-1], segs[1:])]
    return Timing(
        leading_silence_s=round(segs[0][0], 3),
        trailing_silence_s=round(max(0.0, dur - segs[-1][1]), 3),
        speech_s=round(sum(b - a for a, b in segs), 3),
        max_internal_gap_s=round(max(gaps) if gaps else 0.0, 3),
        segments=[(round(a, 3), round(b, 3)) for a, b in segs],
    )


def split_for_stt(x: np.ndarray, sr: int, max_s: float = 28.0) -> list[np.ndarray]:
    """Cut at silences into chunks <= max_s (Prisma REST takes clips up to 30 s)."""
    total = len(x) / sr
    if total <= max_s:
        return [x]
    segs = segments(x, sr)
    cut_points = [0.0]
    last = 0.0
    for a, b in zip(segs[:-1], segs[1:]):
        mid = (a[1] + b[0]) / 2
        if mid - last > max_s * 0.8:
            cut_points.append(mid)
            last = mid
    cut_points.append(total)
    chunks = []
    for a, b in zip(cut_points[:-1], cut_points[1:]):
        while b - a > max_s:                       # no silence available: hard cut
            chunks.append(x[int(a * sr): int((a + max_s) * sr)])
            a += max_s
        chunks.append(x[int(a * sr): int(b * sr)])
    return [c for c in chunks if len(c) > sr * 0.1]
