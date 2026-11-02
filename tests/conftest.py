import pytest


@pytest.fixture(autouse=True)
def offline_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAKRAVYUH_OFFLINE", "1")
    monkeypatch.setenv("CHAKRAVYUH_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("CHAKRAVYUH_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("CHAKRAVYUH_VOICES", str(tmp_path / "voices"))
    yield
