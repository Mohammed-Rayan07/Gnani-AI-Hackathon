"""Gnani Timbre text-to-speech + voice cloning.

TTS:   POST /api/v1/tts/inference  {text, voice, model, language, audio_config}
Clone: POST /api/v1/tts/voice-clone/embeddings (5-30 s of clean audio) -> speaker embedding;
       synthesize with model=TIMBRE_VC_MODEL ("vachana-vc-v1") + speaker_embedding.

Payload shape follows Gnani's LiveKit plugin; the clone request/response field
names are configurable because only the docs pages (not the plugin) cover them.
Only ever clone your own voice, with consent recorded in docs/CONSENT.md.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import httpx
import numpy as np

from .. import audio
from ..cache import DiskCache, key
from ..config import Settings
from ..ledger import Ledger
from ._http import request_with_retry

log = logging.getLogger("chakravyuh.timbre")


def _find_embedding(obj):
    """Return the speaker embedding from a clone response.

    The live API (docs.gnani.ai/api/VC/voice-clone-embeddings) returns
    data.voice_clone_embedding = {"embedding": "<string>", "shape": [1, 768], "dtype": "torch.bfloat16"},
    and vc-inference wants that whole object back as `speaker_embedding`. A bare
    numeric list is still accepted for older/other shapes."""
    if isinstance(obj, dict) and isinstance(obj.get("embedding"), str) and obj["embedding"]:
        return {k: obj[k] for k in ("embedding", "shape", "dtype") if k in obj}
    if isinstance(obj, list) and obj and (
        all(isinstance(v, (int, float)) for v in obj)
        or all(isinstance(v, list) and v and all(isinstance(u, (int, float)) for u in v) for v in obj)
    ):
        return obj
    if isinstance(obj, dict):
        for k in ("voice_clone_embedding", "speaker_embedding", "embedding", "embeddings", "data"):
            if k in obj:
                found = _find_embedding(obj[k])
                if found is not None:
                    return found
        for v in obj.values():
            found = _find_embedding(v)
            if found is not None:
                return found
    return None


def _decode_audio(content: bytes, content_type: str, sr: int) -> tuple[np.ndarray, int]:
    if content[:4] == b"RIFF":
        return audio.read_wav_bytes(content)
    if "json" in content_type or content[:1] in (b"{", b"["):
        obj = json.loads(content)
        for k in ("audio", "audio_content", "audioContent", "data"):
            v = obj.get(k) if isinstance(obj, dict) else None
            if isinstance(v, str):
                return _decode_audio(base64.b64decode(v), "", sr)
        raise ValueError(f"Timbre returned JSON without audio: {str(obj)[:300]}")
    return audio.pcm16_bytes_to_f32(content), sr


class TimbreClient:
    def __init__(self, s: Settings, ledger: Ledger, cache: DiskCache):
        self.s = s
        self.ledger = ledger
        self.cache = cache
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0))
        self._embeddings: dict[str, list] = {}

    def label(self, voice: str) -> str:
        return f"{self.s.tts_vc_model} (cloned: {voice[6:]})" if voice.startswith("clone:") else f"{self.s.tts_model}/{voice}"

    def _embedding(self, name: str) -> dict | list:
        if name not in self._embeddings:
            p = self.s.voices_dir / f"{name}.json"
            if not p.exists():
                raise FileNotFoundError(f"No voice embedding {p}. Run: chakravyuh clone-voice <wav> --name {name}")
            self._embeddings[name] = json.loads(p.read_text())["embedding"]
        return self._embeddings[name]

    def _payload(self, text: str, voice: str, language: str | None) -> dict:
        audio_config = {
            "sample_rate": self.s.tts_sample_rate,
            "encoding": "linear_pcm",
            "num_channels": 1,
            "sample_width": 2,
            "container": "wav",
        }
        if voice.startswith("clone:"):
            payload = {"text": text, "model": self.s.tts_vc_model, "speaker_embedding": self._embedding(voice[6:]),
                       "audio_config": audio_config}
        else:
            payload = {"text": text, "voice": voice, "model": self.s.tts_model, "audio_config": audio_config}
        # `language` is required for timbre-v2.5/v3.0; the vc-inference docs list no language field.
        if language and not voice.startswith("clone:"):
            payload["language"] = language
        return payload

    async def synthesize(self, text: str, *, voice: str, language: str | None = None) -> tuple[np.ndarray, int]:
        payload = self._payload(text, voice, language)
        k = key("timbre", payload)
        hit = self.cache.get_bytes(k, "wav")
        if hit is not None:
            return audio.read_wav_bytes(hit)
        cost = self.ledger.rates.tts(len(text))
        with self.ledger.reserve("tts", len(text), cost, meta=f"{voice} {language} {len(text)}ch"):
            r = await request_with_retry(
                self._http, "POST", f"{self.s.gnani_base_url}/api/v1/tts/inference",
                what="Timbre TTS",
                headers={"X-API-Key-ID": self.s.gnani_api_key, "Content-Type": "application/json"},
                json=payload,
            )
        x, sr = _decode_audio(r.content, r.headers.get("content-type", ""), self.s.tts_sample_rate)
        self.cache.put_bytes(k, audio.wav_bytes(x, sr), "wav")
        return x, sr

    async def create_embedding(self, wav_path: Path, name: str) -> Path:
        x, sr = audio.read_wav(wav_path)
        dur = len(x) / sr
        if not 5.0 <= dur <= 30.0:
            raise ValueError(f"Clone sample must be 5-30 s of clean speech; got {dur:.1f}s")
        wav = audio.wav_bytes(audio.resample(x, sr, 16000), 16000)
        with self.ledger.reserve("voice_clone", 1, self.ledger.rates.vc_per_call, meta=name):
            r = await request_with_retry(
                self._http, "POST", f"{self.s.gnani_base_url}/api/v1/tts/voice-clone/embeddings",
                what="Timbre voice clone",
                headers={"X-API-Key-ID": self.s.gnani_api_key},
                files={self.s.vc_upload_field: ("sample.wav", wav, "audio/wav")},
            )
        emb = _find_embedding(r.json())
        if emb is None:
            raise ValueError(f"Could not find an embedding in the response: {r.text[:300]}")
        self.s.voices_dir.mkdir(parents=True, exist_ok=True)
        out = self.s.voices_dir / f"{name}.json"
        out.write_text(json.dumps({"name": name, "source_seconds": round(dur, 1), "embedding": emb}))
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
