"""Timbre v2.5 voice catalogue, from docs.gnani.ai/api/TTS/available-voices (checked 2026-11-05).

Every v2.5 voice has ONE preferred `language`; a mismatched language is accepted
but sounds worse, so pick voices by language. v2.5 voices are rejected by
timbre-v3.0 and vice versa.
"""

from __future__ import annotations

# name -> (gender, preferred language)
V25: dict[str, tuple[str, str]] = {
    "Kaveri": ("f", "en-IN"), "Trupti": ("f", "en-IN"), "Devika": ("f", "en-IN"),
    "Pranav": ("m", "en-IN"), "Shlok": ("m", "en-IN"), "Girish": ("m", "en-IN"),
    "Nalini": ("f", "hi-IN"), "Bhavna": ("f", "hi-IN"), "Yashvi": ("f", "hi-IN"), "Urmila": ("f", "hi-IN"),
    "Jwala": ("f", "hi-IN"), "Chitra": ("f", "hi-IN"), "Ambuja": ("f", "hi-IN"),
    "Deepak": ("m", "hi-IN"), "Roopesh": ("m", "hi-IN"), "Vikrant": ("m", "hi-IN"), "Hemraj": ("m", "hi-IN"),
    "Jalaj": ("m", "hi-IN"), "Omkar": ("m", "hi-IN"),
    "Poorvi": ("f", "hi-en"),
    "Asmita": ("f", "ta-IN"), "Trisha": ("f", "ta-IN"), "Brinda": ("f", "ta-IN"), "Vedika": ("f", "ta-IN"),
    "Noopur": ("f", "ta-IN"),
    "Suhana": ("f", "te-IN"), "Lehara": ("f", "te-IN"), "Lavanya": ("f", "te-IN"), "Yukti": ("f", "te-IN"),
    "Varuni": ("f", "te-IN"),
    "Saanvi": ("f", "kn-IN"), "Kavin": ("m", "kn-IN"),
    "Reshma": ("f", "ml-IN"), "Riyaan": ("m", "ml-IN"),
    "Zahira": ("f", "mr-IN"), "Ishaan": ("m", "mr-IN"),
    "Kirra": ("f", "bn-IN"), "Dhruva": ("m", "bn-IN"),
    "Falak": ("f", "gu-IN"), "Veera": ("m", "gu-IN"),
    "Mehuli": ("f", "pa-IN"), "Zayan": ("m", "pa-IN"),
}

# The reference bank bot speaks with a professional female voice in each reply language.
REFBOT_BY_LANGUAGE = {"en-IN": "Kaveri", "hi-IN": "Ambuja", "ta-IN": "Vedika", "kn-IN": "Saanvi",
                      "bn-IN": "Kirra", "te-IN": "Varuni", "ml-IN": "Reshma", "mr-IN": "Zahira",
                      "gu-IN": "Falak", "pa-IN": "Mehuli"}

DEFAULT_VOICE = "Deepak"  # Hindi, male


def language_of(voice: str) -> str | None:
    v = V25.get(voice)
    return v[1] if v else None


def for_language(language: str | None, gender: str | None = None) -> list[str]:
    """Voices whose preferred language matches (hi-en falls back to hi-IN voices too)."""
    lang = (language or "").strip()
    langs = {lang, "hi-IN"} if lang == "hi-en" else {lang}
    return [n for n, (g, l) in V25.items() if l in langs and (gender is None or g == gender)]


def pick(language: str | None, gender: str | None = None) -> str:
    return (for_language(language, gender) or for_language(language) or [DEFAULT_VOICE])[0]


def refbot_voice(language: str | None) -> str:
    return REFBOT_BY_LANGUAGE.get(language or "", REFBOT_BY_LANGUAGE["en-IN"])
