"""Typed schemas for personas, scenarios, turns, calls and verdicts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .config import ROOT


class Persona(BaseModel):
    id: str
    name: str
    summary: str                                  # one line, shown on the scorecard
    background: str                               # who they are, why they call
    speaking_style: str                           # code-mix pattern, pace, temper
    languages: list[str]                          # BCP-47, e.g. ["hi-IN", "en-IN"]
    script: Literal["latin", "devanagari", "tamil", "kannada", "bengali", "telugu", "malayalam", "gujarati", "gurmukhi", "mixed"] = "mixed"
    expected_reply_language: str                  # what a good bot should mirror: "hi-en", "ta-en", "hi", "kn", "en"
    tts_language: str                             # Timbre v2.5 language code
    voice: str = "Pranav"                         # Timbre voice name, or "clone:<name>" for an embedding in voices/
    fallback_voice: str = "Pranav"                # used (and reported) when the clone embedding is missing
    channel: str = "city_4g"
    adversarial: bool = False                     # social-engineering persona: never run against third-party bots
    sample_lines: list[str] = Field(default_factory=list)
    tactics: list[str] = Field(default_factory=list)
    generated_by: str | None = None               # model attribution for comment-loop callers
    language_note: str | None = None              # honest note when a requested language was mapped

    @classmethod
    def load(cls, path: Path) -> "Persona":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class Canary(BaseModel):
    label: str
    value: str                                    # the fake identifier as stored, e.g. "FAKE-0000-7342-4417"
    kind: Literal["digits", "token"] = "digits"
    min_match: int = 6                            # digits: this many consecutive canary digits = leak


class Scenario(BaseModel):
    id: str
    title: str
    caller_goal: str                              # what the caller is trying to do (persona LLM sees this)
    adversarial_goal: str | None = None           # goal used instead when the persona is adversarial
    hidden_facts: dict = Field(default_factory=dict)   # what the caller knows (fake customer data)
    ground_truth: dict = Field(default_factory=dict)   # what a correct bot should say (judge sees this)
    success_criteria: list[str]                   # judge rubric for task success
    policy_rules: list[str] = Field(default_factory=list)
    canaries: list[Canary] = Field(default_factory=list)
    social_engineering: bool = False
    max_turns: int = 8
    offline_script: list[str] = Field(default_factory=list)  # caller lines for dry runs only

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


class TurnTiming(BaseModel):
    response_latency_s: float | None = None       # t_first_byte - t_send (bot side)
    total_s: float | None = None                  # t_done - t_send
    leading_silence_s: float | None = None        # inside the bot's audio
    max_internal_gap_s: float | None = None
    bot_speech_s: float | None = None


class Turn(BaseModel):
    index: int
    caller_text: str                              # what the persona LLM said
    caller_intent: str = ""
    caller_lang: str = ""
    bot_heard_caller: str | None = None           # what the bot's STT heard (if the bot exposes it)
    bot_text_true: str | None = None              # the bot's real reply text (if exposed): harness noise floor
    bot_text_heard: str = ""                      # Prisma transcript of the bot through the line
    bot_detected_lang: str | None = None
    bot_end_call: bool = False
    timing: TurnTiming = Field(default_factory=TurnTiming)
    audio: dict[str, str] = Field(default_factory=dict)   # name -> relative wav path
    channel_meta: dict = Field(default_factory=dict)


class CallRecord(BaseModel):
    call_id: str
    run_id: str
    persona_id: str
    scenario_id: str
    seed: int
    channel: str
    bot_label: str
    bot_version: str
    mode: str                                     # "LIVE ..." | "OFFLINE DRY RUN ..."
    adapter: str                                  # "audio-http" | "text-http (logic-only)" | "inprocess"
    models: dict[str, str] = Field(default_factory=dict)  # role -> model attribution
    turns: list[Turn] = Field(default_factory=list)
    ended_by: Literal["caller", "bot", "turn_cap", "error"] = "turn_cap"
    error: str | None = None


class CriterionResult(BaseModel):
    name: str
    status: Literal["pass", "fail", "na", "unverified"]
    reason: str = ""
    evidence: list[dict] = Field(default_factory=list)   # [{"turn": i, "quote": "..."}]
    source: Literal["deterministic", "llm"] = "deterministic"


class CallVerdict(BaseModel):
    call_id: str
    persona_id: str
    scenario_id: str
    seed: int
    bot_version: str
    passed: bool
    criteria: list[CriterionResult]
    failure_kind: Literal["none", "bot", "harness", "review"] = "none"
    judge_model: str = ""


def load_dir(kind: type[BaseModel], sub: str) -> dict[str, BaseModel]:
    out = {}
    for p in sorted((ROOT / sub).glob("*.yaml")):
        obj = kind.load(p)  # type: ignore[attr-defined]
        out[obj.id] = obj
    return out


def personas() -> dict[str, Persona]:
    return load_dir(Persona, "personas")  # type: ignore[return-value]


def scenarios() -> dict[str, Scenario]:
    return load_dir(Scenario, "scenarios")  # type: ignore[return-value]
