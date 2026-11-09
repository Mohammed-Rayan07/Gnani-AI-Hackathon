"""Regressions for fixes found against the live Gnani API (docs/LIVE_STATUS.md)."""

from pathlib import Path

import yaml

from chakravyuh import voices
from chakravyuh.clients.timbre import TimbreClient, _find_embedding

ROOT = Path(__file__).resolve().parents[1]

DOCS_CLONE_RESPONSE = {
    "success": True, "message": "Voice embeddings generated successfully",
    "data": {"voice_clone_embedding": {"embedding": "abc123==", "shape": [1, 768], "dtype": "torch.bfloat16"}},
}


def test_clone_embedding_is_the_documented_object():
    emb = _find_embedding(DOCS_CLONE_RESPONSE)
    assert emb == {"embedding": "abc123==", "shape": [1, 768], "dtype": "torch.bfloat16"}


def test_clone_embedding_numeric_list_still_works():
    assert _find_embedding({"embedding": [0.1, 0.2]}) == [0.1, 0.2]


def test_clone_payload_sends_object_and_no_language(tmp_path):
    import json

    from chakravyuh.config import get_settings
    s = get_settings()
    s.voices_dir = tmp_path
    (tmp_path / "me.json").write_text(json.dumps({"embedding": DOCS_CLONE_RESPONSE["data"]["voice_clone_embedding"]}))
    t = TimbreClient(s, ledger=None, cache=None)
    p = t._payload("hello", "clone:me", "hi-IN")
    assert p["speaker_embedding"]["shape"] == [1, 768] and "language" not in p
    assert t._payload("hello", "Deepak", "hi-IN")["language"] == "hi-IN"


def test_persona_voices_exist_in_timbre_v25_and_match_language():
    for f in sorted((ROOT / "personas").glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        for v in (d.get("voice"), d.get("fallback_voice")):
            if v and not v.startswith("clone:"):
                assert v in voices.V25, f"{f.name}: {v} is not a Timbre v2.5 voice"
                assert voices.language_of(v) == d["tts_language"], f"{f.name}: {v} prefers {voices.language_of(v)}"


def test_refbot_voice_matches_reply_language():
    for lang, v in voices.REFBOT_BY_LANGUAGE.items():
        assert voices.language_of(v) == lang
    assert voices.refbot_voice("xx-XX") == "Kaveri"


def test_site_names_only_models_that_ran(tmp_path):
    from chakravyuh.site import _built_on
    run = tmp_path / "r"
    (run / "calls" / "c1").mkdir(parents=True)
    (run / "calls" / "c1" / "call.json").write_text('{"models": {"caller_voice": "timbre-v2.5/Jalaj"}}', encoding="utf-8")
    assert _built_on([run]) == "Gnani Prisma and Timbre"
    (run / "calls" / "c1" / "call.json").write_text('{"models": {"caller_voice": "vachana-vc-v1 (cloned: me)"}}', encoding="utf-8")
    (run / "summary.evon.json").write_text("{}", encoding="utf-8")
    assert _built_on([run]) == "Gnani Prisma, Timbre (plus voice cloning) and Evon"
