import numpy as np
import pytest

from chakravyuh import channel


def tone(seconds=2.0, sr=16000):
    t = np.arange(int(sr * seconds)) / sr
    return (0.3 * np.sin(2 * np.pi * 300 * t) * (np.sin(2 * np.pi * 2 * t) > 0)).astype(np.float32), sr


@pytest.mark.parametrize("profile", list(channel.PROFILES))
def test_degrade_is_8k_and_deterministic(profile):
    x, sr = tone()
    a = channel.degrade(x, sr, profile, seed=3)
    b = channel.degrade(x, sr, profile, seed=3)
    assert a.sr == 8000
    assert len(a.audio) == int(len(x) / 2)
    assert np.array_equal(a.audio, b.audio)
    assert np.max(np.abs(a.audio)) <= 1.0


def test_seed_changes_noise():
    x, sr = tone()
    assert not np.array_equal(channel.degrade(x, sr, "city_4g", 1).audio, channel.degrade(x, sr, "city_4g", 2).audio)


def test_gilbert_elliott_mean_loss_close_to_target():
    rng = np.random.default_rng(0)
    mask = channel.gilbert_elliott_mask(200_000, 0.08, 3.0, rng)
    assert 0.07 < mask.mean() < 0.09
    # bursty: mean run length of lost frames should be near 3
    runs, cur = [], 0
    for v in mask:
        if v:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    assert 2.5 < np.mean(runs) < 3.5


def test_snr_mixing_hits_target():
    rng = np.random.default_rng(1)
    s = rng.standard_normal(16000).astype(np.float32) * 0.1
    n = rng.standard_normal(16000).astype(np.float32)
    y = channel.mix_at_snr(s, n, 16000, 10.0)
    noise = y - s
    snr = 10 * np.log10(np.mean(s.astype(np.float64) ** 2) / np.mean(noise.astype(np.float64) ** 2))
    assert abs(snr - 10.0) < 0.5


def test_mulaw_roundtrip_small_error():
    x = np.linspace(-0.9, 0.9, 1000).astype(np.float32)
    assert np.max(np.abs(channel.mulaw_roundtrip(x) - x)) < 0.05


def test_clean_line_without_ambient_has_no_noise_meta():
    x, sr = tone()
    r = channel.degrade(x, sr, "rural_2g", seed=1, ambient=False)
    assert "snr_db" not in r.meta
