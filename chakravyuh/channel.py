"""Phone-line simulator.

Upstream (caller -> bot):   ambient noise @ target SNR -> 300-3400 Hz band-pass
                            -> 8 kHz -> AGC/clipping -> codec (mu-law | opus-8k)
                            -> Gilbert-Elliott burst packet loss (20 ms frames)
Downstream (bot -> caller): the same line, without the caller's ambient noise.

Everything is seeded, so a call replays bit-for-bit.

What this is NOT (say so in interviews): real AMR/GSM codec artefacts, echo,
carrier AGC, jitter-buffer time warping. Real calls are the validation step.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

from . import audio
from .config import ROOT

LINE_SR = 8000
NOISE_DIR = ROOT / "assets" / "noise"


@dataclass(frozen=True)
class ChannelProfile:
    name: str
    snr_db: float | None          # None = no ambient noise
    noise: tuple[str, ...]        # noise bed kinds mixed together
    loss_rate: float              # mean frame loss rate
    mean_burst_frames: float      # mean length of a loss burst (Gilbert-Elliott)
    codec: str                    # "mulaw" | "opus8k"
    clip_gain_db: float = 0.0     # pre-codec gain; >0 drives clipping (cheap handset AGC)
    description: str = ""


PROFILES: dict[str, ChannelProfile] = {
    "clean_pstn": ChannelProfile(
        "clean_pstn", 25.0, ("room",), 0.0, 1.0, "mulaw",
        description="Control: quiet room, G.711 mu-law, no loss.",
    ),
    "city_4g": ChannelProfile(
        "city_4g", 12.0, ("traffic",), 0.01, 2.0, "mulaw",
        description="Street traffic at 12 dB SNR, 1% bursty loss.",
    ),
    "rural_2g": ChannelProfile(
        "rural_2g", 5.0, ("market", "fan"), 0.08, 3.0, "opus8k", clip_gain_db=9.0,
        description="Market babble + fan at 5 dB SNR, 8% bursty loss, low-bitrate opus, clipping.",
    ),
}


# ----------------------------------------------------------------------------- noise beds

def _colored_noise(n: int, rng: np.random.Generator, exponent: float) -> np.ndarray:
    """1/f^exponent noise (0 = white, 1 = pink, 2 = brown)."""
    spec = rng.standard_normal(n // 2 + 1) + 1j * rng.standard_normal(n // 2 + 1)
    f = np.arange(len(spec), dtype=np.float64)
    f[0] = 1.0
    spec /= f ** (exponent / 2.0)
    x = np.fft.irfft(spec, n)
    return (x / (np.max(np.abs(x)) + 1e-9)).astype(np.float32)


def _synthetic_bed(kind: str, n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / sr
    if kind == "room":
        return _colored_noise(n, rng, 1.0) * 0.3
    if kind == "fan":
        hum = 0.2 * np.sin(2 * np.pi * 120 * t) * (1 + 0.1 * np.sin(2 * np.pi * 0.5 * t))
        return (_colored_noise(n, rng, 0.8) + hum).astype(np.float32)
    if kind == "traffic":
        rumble = _colored_noise(n, rng, 2.0)
        swell = 0.6 + 0.4 * np.sin(2 * np.pi * rng.uniform(0.05, 0.2) * t + rng.uniform(0, 6.28))
        x = rumble * swell + 0.3 * _colored_noise(n, rng, 1.0)
        # occasional two-tone horn blasts; an Indian street is never quiet for long
        for _ in range(max(1, int(n / sr / 4))):
            start = int(rng.uniform(0, max(1, n - sr * 0.6)))
            length = int(sr * rng.uniform(0.25, 0.6))
            tt = np.arange(length) / sr
            f0 = rng.uniform(380, 520)
            horn = sum(np.sin(2 * np.pi * f0 * k * tt) / k for k in (1, 2, 3)) + sum(
                np.sin(2 * np.pi * f0 * 1.26 * k * tt) / k for k in (1, 2)
            )
            env = np.minimum(1, np.minimum(tt / 0.02, (tt[-1] - tt) / 0.03 + 1e-9))
            x[start:start + length] += (0.8 * horn * env).astype(np.float32)[: len(x[start:start + length])]
        return x.astype(np.float32)
    if kind == "market":
        # babble-like texture with no actual speech (no bystander voices in a public repo)
        x = np.zeros(n, dtype=np.float32)
        for _ in range(6):
            band = _colored_noise(n, rng, 0.5)
            rate = rng.uniform(3.0, 6.0)
            env = np.clip(np.sin(2 * np.pi * rate * t + rng.uniform(0, 6.28)), 0, None) ** 2
            x += band * env.astype(np.float32)
        return x
    raise ValueError(f"unknown noise kind {kind!r}")


def noise_bed(kind: str, n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    """A recorded CC0 bed from assets/noise/<kind>*.wav if present, else a synthetic one."""
    files = sorted(NOISE_DIR.glob(f"{kind}*.wav")) if NOISE_DIR.exists() else []
    if files:
        x, file_sr = audio.read_wav(files[int(rng.integers(len(files)))])
        x = audio.resample(x, file_sr, sr)
        if len(x) < n:
            x = np.tile(x, int(np.ceil(n / len(x))))
        start = int(rng.integers(0, len(x) - n + 1))
        return x[start:start + n]
    return _synthetic_bed(kind, n, sr, rng)


# ----------------------------------------------------------------------------- line stages

def _active_power(x: np.ndarray, sr: int) -> float:
    """Speech power over active 20 ms frames, so leading silence does not inflate SNR."""
    frame = int(0.02 * sr)
    if len(x) < frame:
        return float(np.mean(x.astype(np.float64) ** 2) + 1e-12)
    frames = x[: len(x) // frame * frame].reshape(-1, frame).astype(np.float64)
    p = np.mean(frames ** 2, axis=1)
    thresh = max(p.max() * 10 ** (-40 / 10), 1e-10)
    active = p[p > thresh]
    return float(active.mean() if len(active) else p.mean()) + 1e-12


def mix_at_snr(speech: np.ndarray, noise: np.ndarray, sr: int, snr_db: float) -> np.ndarray:
    ps = _active_power(speech, sr)
    pn = float(np.mean(noise.astype(np.float64) ** 2)) + 1e-12
    scale = np.sqrt(ps / (pn * 10 ** (snr_db / 10)))
    return (speech + noise * scale).astype(np.float32)


def bandpass(x: np.ndarray, sr: int, lo: float = 300.0, hi: float = 3400.0) -> np.ndarray:
    sos = butter(4, [lo, min(hi, sr / 2 * 0.95)], btype="band", fs=sr, output="sos")
    return sosfiltfilt(sos, x).astype(np.float32)


MU = 255.0


def mulaw_roundtrip(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -1.0, 1.0)
    y = np.sign(x) * np.log1p(MU * np.abs(x)) / np.log1p(MU)
    q = np.round((y + 1) / 2 * 255) / 255 * 2 - 1           # 8-bit quantisation
    return (np.sign(q) * ((1 + MU) ** np.abs(q) - 1) / MU).astype(np.float32)


def opus8k_roundtrip(x: np.ndarray, bitrate: str = "6k") -> np.ndarray | None:
    """Narrowband opus via ffmpeg. Returns None when ffmpeg/libopus is unavailable."""
    if not shutil.which("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory() as d:
        src, enc, dst = Path(d) / "in.wav", Path(d) / "x.ogg", Path(d) / "out.wav"
        audio.write_wav(src, x, LINE_SR)
        try:
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-c:a", "libopus",
                 "-b:a", bitrate, "-application", "voip", str(enc)],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-i", str(enc), "-ar", str(LINE_SR), "-ac", "1", str(dst)],
                check=True, capture_output=True,
            )
        except subprocess.CalledProcessError:
            return None
        y, sr = audio.read_wav(dst)
    y = audio.resample(y, sr, LINE_SR)
    # codec delay: pad/trim to the original length
    return np.pad(y, (0, max(0, len(x) - len(y))))[: len(x)].astype(np.float32)


def gilbert_elliott_mask(n_frames: int, loss_rate: float, mean_burst: float, rng: np.random.Generator) -> np.ndarray:
    """True = frame lost. Two-state Markov chain with the requested mean loss and burst length."""
    lost = np.zeros(n_frames, dtype=bool)
    if loss_rate <= 0 or n_frames == 0:
        return lost
    r = 1.0 / max(mean_burst, 1.0)                 # P(bad -> good)
    p = loss_rate * r / max(1e-9, 1.0 - loss_rate)  # P(good -> bad)
    bad = rng.random() < loss_rate
    u = rng.random(n_frames)
    for i in range(n_frames):
        lost[i] = bad
        bad = (u[i] >= r) if bad else (u[i] < p)
    return lost


def apply_packet_loss(x: np.ndarray, mask: np.ndarray, sr: int, frame_ms: int = 20) -> np.ndarray:
    """Lost frames get naive concealment: first lost frame repeats the last good one at half gain, then silence."""
    frame = int(sr * frame_ms / 1000)
    y = x.copy()
    prev_good = np.zeros(frame, dtype=np.float32)
    run = 0
    fade = np.linspace(1, 0, frame, dtype=np.float32)
    for i, is_lost in enumerate(mask):
        seg = slice(i * frame, min((i + 1) * frame, len(y)))
        m = seg.stop - seg.start
        if m <= 0:
            break
        if is_lost:
            y[seg] = (prev_good[:m] * 0.5 * fade[:m]) if run == 0 else 0.0
            run += 1
        else:
            prev_good = x[seg].copy() if m == frame else np.pad(x[seg], (0, frame - m))
            run = 0
    return y


def soft_clip(x: np.ndarray, gain_db: float) -> np.ndarray:
    if gain_db <= 0:
        return x
    g = 10 ** (gain_db / 20)
    return (np.tanh(x * g) / np.tanh(g) * 0.95).astype(np.float32)


# ----------------------------------------------------------------------------- public API

@dataclass
class ChannelResult:
    audio: np.ndarray        # float32 @ 8 kHz
    sr: int
    meta: dict


def degrade(x: np.ndarray, sr: int, profile: ChannelProfile | str, seed: int, *, ambient: bool = True) -> ChannelResult:
    prof = PROFILES[profile] if isinstance(profile, str) else profile
    rng = np.random.default_rng(seed)
    x16 = audio.resample(audio.to_mono_f32(x), sr, 16000)
    meta: dict = {"profile": prof.name, "seed": seed, "ambient": ambient}

    if ambient and prof.snr_db is not None and len(x16):
        bed = sum(noise_bed(k, len(x16), 16000, rng) for k in prof.noise)
        x16 = mix_at_snr(x16, bed, 16000, prof.snr_db)
        meta["snr_db"] = prof.snr_db
        meta["noise"] = list(prof.noise)

    y = bandpass(x16, 16000) if len(x16) > 64 else x16
    y = audio.resample(y, 16000, LINE_SR)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0:
        y = y / peak * 0.7                                   # handset AGC
    y = soft_clip(y, prof.clip_gain_db)

    codec = prof.codec
    if codec == "opus8k":
        o = opus8k_roundtrip(y)
        if o is None:
            codec = "mulaw (opus unavailable)"
            y = mulaw_roundtrip(y)
        else:
            y = o
    else:
        y = mulaw_roundtrip(y)
    meta["codec"] = codec

    frame = int(LINE_SR * 0.02)
    n_frames = int(np.ceil(len(y) / frame))
    mask = gilbert_elliott_mask(n_frames, prof.loss_rate, prof.mean_burst_frames, rng)
    y = apply_packet_loss(y, mask, LINE_SR)
    meta["frames"] = n_frames
    meta["lost_frames"] = int(mask.sum())
    meta["measured_loss"] = round(float(mask.mean()) if n_frames else 0.0, 4)
    return ChannelResult(y.astype(np.float32), LINE_SR, meta)


def profile_table() -> list[dict]:
    return [asdict(p) for p in PROFILES.values()]
