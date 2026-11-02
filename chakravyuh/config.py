"""Settings, loaded from environment variables (and an optional .env file).

Nothing here is secret-bearing except the API keys, which only ever come from
the environment. See .env.example for every knob.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader: KEY=VALUE lines; real env vars win."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class LLMRole:
    """One OpenAI-compatible chat endpoint (vLLM-served Evon, Ollama GGUF, or a hosted LLM)."""

    role: str
    base_url: str
    model: str
    api_key: str = ""
    json_mode: bool = True
    extra_body: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human-readable model attribution used in every report and reply."""
        return self.model or "unset"

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)


def _llm_role(role: str) -> LLMRole:
    p = role.upper()
    extra = _env(f"{p}_LLM_EXTRA_BODY", "")
    return LLMRole(
        role=role,
        base_url=_env(f"{p}_LLM_BASE_URL").rstrip("/"),
        model=_env(f"{p}_LLM_MODEL"),
        api_key=_env(f"{p}_LLM_API_KEY"),
        json_mode=_env_bool(f"{p}_LLM_JSON_MODE", True),
        extra_body=json.loads(extra) if extra else {},
    )


@dataclass
class Settings:
    offline: bool
    gnani_api_key: str
    gnani_base_url: str
    stt_model: str
    stt_language: str
    stt_format: str
    stt_upload_sr: int
    tts_model: str
    tts_vc_model: str
    tts_sample_rate: int
    vc_upload_field: str
    credit_cap: float
    rate_stt_per_min: float
    rate_tts_per_1k_chars: float
    rate_vc_per_call: float
    confirm_above: float
    concurrency: int
    persona_llm: LLMRole
    bot_llm: LLMRole
    judge_llm: LLMRole
    cache_dir: Path
    runs_dir: Path
    voices_dir: Path

    @property
    def mode_label(self) -> str:
        return "OFFLINE DRY RUN (simulated STT/TTS, numbers are meaningless)" if self.offline else "LIVE (Gnani APIs)"


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        offline=_env_bool("CHAKRAVYUH_OFFLINE", False),
        gnani_api_key=_env("GNANI_API_KEY"),
        gnani_base_url=_env("GNANI_BASE_URL", "https://api.vachana.ai").rstrip("/"),
        stt_model=_env("PRISMA_MODEL", "prisma-v3.0"),
        stt_language=_env("PRISMA_LANGUAGE", "indic-auto"),
        stt_format=_env("PRISMA_FORMAT", "codemix"),
        stt_upload_sr=int(_env("PRISMA_UPLOAD_SR", "8000")),
        tts_model=_env("TIMBRE_MODEL", "timbre-v2.5"),
        tts_vc_model=_env("TIMBRE_VC_MODEL", "vachana-vc-v1"),
        tts_sample_rate=int(_env("TIMBRE_SAMPLE_RATE", "16000")),
        vc_upload_field=_env("VC_UPLOAD_FIELD", "audio_file"),
        credit_cap=float(_env("CREDIT_CAP", "4000")),
        rate_stt_per_min=float(_env("RATE_STT_PER_MIN", "0.5")),
        rate_tts_per_1k_chars=float(_env("RATE_TTS_PER_1K_CHARS", "2.8")),
        rate_vc_per_call=float(_env("RATE_VC_PER_CALL", "1.0")),
        confirm_above=float(_env("CONFIRM_ABOVE", "200")),
        concurrency=int(_env("CONCURRENCY", "6")),
        persona_llm=_llm_role("persona"),
        bot_llm=_llm_role("bot"),
        judge_llm=_llm_role("judge"),
        cache_dir=Path(_env("CHAKRAVYUH_CACHE", str(ROOT / ".cache"))),
        runs_dir=Path(_env("CHAKRAVYUH_RUNS", str(ROOT / "runs"))),
        voices_dir=Path(_env("CHAKRAVYUH_VOICES", str(ROOT / "voices"))),
    )
