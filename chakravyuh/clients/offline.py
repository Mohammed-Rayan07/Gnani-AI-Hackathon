"""Offline stand-ins so the full pipeline can be exercised without network or credits.

They exist for tests and plumbing dry runs ONLY. Every artefact produced in
offline mode is stamped "OFFLINE DRY RUN"; never quote these numbers anywhere.

- OfflineTTS makes deterministic speech-like audio (harmonic syllables with
  pauses at word boundaries), so VAD, the channel and timing code all run.
- OfflineSTT cannot decode audio. It returns the reference text, dropping words
  in proportion to how much of the speech was destroyed by packet loss.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

from ..vad import speech_mask
from .prisma import STTResult

SR = 16000


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "little")


class OfflineTTS:
    def label(self, voice: str) -> str:
        return f"offline-tts/{voice}"

    async def synthesize(self, text: str, *, voice: str, language: str | None = None) -> tuple[np.ndarray, int]:
        rng = np.random.default_rng(_seed(text, voice, language))
        f0 = 110 + (_seed(voice) % 120)
        out = [np.zeros(int(0.15 * SR), dtype=np.float32)]
        for word in text.split():
            n = int(SR * min(0.6, 0.06 * len(word) + 0.08))
            t = np.arange(n) / SR
            pitch = f0 * (1 + 0.08 * np.sin(2 * np.pi * rng.uniform(2, 5) * t))
            phase = 2 * np.pi * np.cumsum(pitch) / SR
            sig = sum(np.sin(k * phase) / k for k in range(1, 6))
            env = np.sin(np.pi * np.clip(t / t[-1], 0, 1)) ** 0.5
            out.append((0.25 * sig * env).astype(np.float32))
            out.append(np.zeros(int(SR * (0.25 if re.search(r"[.?!,।]$", word) else 0.07)), dtype=np.float32))
        out.append(np.zeros(int(0.2 * SR), dtype=np.float32))
        return np.concatenate(out), SR

    async def create_embedding(self, *a, **kw):
        raise RuntimeError("Voice cloning needs the live API")

    async def aclose(self) -> None:
        pass


def _script_lang(text: str) -> str:
    if re.search(r"[ऀ-ॿ]", text):
        return "hi-IN"
    if re.search(r"[஀-௿]", text):
        return "ta-IN"
    if re.search(r"[ಀ-೿]", text):
        return "kn-IN"
    if re.search(r"[ঀ-৿]", text):
        return "bn-IN"
    return "en-IN"


class OfflineSTT:
    label = "offline-stt (reference text + simulated word drops)"

    async def transcribe(self, x: np.ndarray, sr: int, *, language: str | None = None, reference_text: str | None = None) -> STTResult:
        if reference_text is None:
            return STTResult("", None)
        frame = int(sr * 0.02)
        n = len(x) // frame
        frames = x[: n * frame].reshape(n, frame) if n else np.zeros((0, frame))
        dead = float(np.mean(np.max(np.abs(frames), axis=1) < 1e-6)) if n else 0.0
        drop_p = min(0.6, 0.02 + 1.5 * dead)
        rng = np.random.default_rng(_seed(reference_text, len(x)))
        words = [w for w in reference_text.split() if rng.random() >= drop_p]
        return STTResult(" ".join(words), _script_lang(reference_text), [{"offline": True, "drop_p": round(drop_p, 3)}])

    async def aclose(self) -> None:
        pass


class OfflineLLM:
    """Marker object: callers check `.offline` and use their scripted/rule-based path."""

    offline = True

    def __init__(self, role: str):
        self.role = role

    @property
    def label(self) -> str:
        return f"offline-{self.role} (scripted)"

    async def aclose(self) -> None:
        pass


def _speech_present(x: np.ndarray, sr: int) -> bool:
    return bool(speech_mask(x, sr).any())
