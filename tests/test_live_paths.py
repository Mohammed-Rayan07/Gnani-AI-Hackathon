"""Live code paths against a local stand-in for Gnani (Prisma, Timbre, voice clone) and an LLM server.

Offline mode swaps in fake clients; this test does NOT. It drives the real PrismaClient, TimbreClient,
LLMClient, voice cloning, the comment loop and the launch pipeline over real HTTP, and the stand-in
validates every request against the API shapes verified live (docs/LIVE_STATUS.md).
"""

import shutil
import socket
import threading
import time

import httpx
import numpy as np
import pytest
import soundfile as sf
import uvicorn
from typer.testing import CliRunner

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def mock_server():
    from tests import mock_apis

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(mock_apis.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=0.2)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", mock_apis
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture
def live_env(mock_server, monkeypatch, tmp_path):
    base, mock = mock_server
    monkeypatch.delenv("CHAKRAVYUH_OFFLINE", raising=False)
    env = {"GNANI_API_KEY": mock.KEY, "GNANI_BASE_URL": base, "CONCURRENCY": "2", "CREDIT_CAP": "4000"}
    for role, model in (("PERSONA", "mock-persona-20b"), ("BOT", "mock-bot-27b"), ("JUDGE", "mock-judge-120b")):
        env |= {f"{role}_LLM_BASE_URL": f"{base}/v1", f"{role}_LLM_MODEL": model, f"{role}_LLM_API_KEY": "x"}
    for k in ("EVON_LLM_BASE_URL", "EVON_LLM_MODEL"):
        env[k] = ""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    wav = tmp_path / "me.wav"
    sr = 16000
    t = np.arange(sr * 12) / sr
    sf.write(wav, (0.3 * np.sin(2 * np.pi * 150 * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype("float32"), sr)
    mock.VIOLATIONS.clear()
    return tmp_path, wav, mock


def test_live_launch_and_comment_loop(live_env):
    from chakravyuh.cli import app

    tmp, wav, mock = live_env
    r = CliRunner().invoke(app, ["launch", "--personas", "uncle_traffic,social_engineer", "--seeds", "1", "--max-turns", "4",
                                 "--steps", "doctor,clone,run,judge,reels,site,kit,video", "--clone", str(wav), "--i-consent",
                                 "--yes", "--site-dir", str(tmp / "site"), "--kit-dir", str(tmp / "launch")])
    assert r.exit_code == 0, r.output
    assert mock.VIOLATIONS == [], mock.VIOLATIONS          # every request matched the verified API shapes
    assert mock.STATS["clone"] == 1 and mock.STATS["vc_tts"] > 0   # cloned voice used for the uncle + VO
    post = (tmp / "launch" / "LINKEDIN_POST.md").read_text()
    assert "OFFLINE" not in post and "The uncle is me, cloned" in post
    assert (tmp / "launch" / "demo_4x5.mp4").stat().st_size > 50_000
    assert (tmp / "site" / "index.html").exists()

    r = CliRunner().invoke(app, ["caller", "my nani who mixes Bhojpuri and Hindi and keeps asking about her pension"])
    assert r.exit_code == 0, r.output
    assert "Bhojpuri isn't supported" in r.output and "Suggested reply" in r.output
    assert mock.VIOLATIONS == [], mock.VIOLATIONS
