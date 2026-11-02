"""The caller's brain: given persona + scenario + what the caller has HEARD so far,
produce the next spoken line. The caller only ever sees the bot through the
noisy line (Prisma's transcript), exactly like a real caller would."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .models import Persona, Scenario

SCRIPT_RULES = {
    "mixed": "Write words of the Indian language in their native script (Hindi in Devanagari, Tamil in Tamil script, etc.) and English words in Latin script, exactly as a code-mixed speaker would type them.",
    "latin": "Write everything in Latin script (romanised).",
    "devanagari": "Write in Devanagari script.",
    "tamil": "Write in Tamil script.",
    "kannada": "Write in Kannada script.",
    "bengali": "Write in Bengali script.",
    "telugu": "Write in Telugu script.",
    "malayalam": "Write in Malayalam script.",
    "gujarati": "Write in Gujarati script.",
    "gurmukhi": "Write in Gurmukhi script.",
}


@dataclass
class CallerTurn:
    utterance: str
    lang: str = ""
    intent: str = ""
    end_call: bool = False


def system_prompt(p: Persona, sc: Scenario) -> str:
    goal = sc.adversarial_goal if (p.adversarial and sc.adversarial_goal) else sc.caller_goal
    facts = {} if p.adversarial else sc.hidden_facts
    return f"""You are role-playing a CALLER phoning a bank's voice bot. This is automated QA testing of the bot; every name and number here is fictional.

WHO YOU ARE: {p.name}. {p.background}
HOW YOU SPEAK: {p.speaking_style}
LANGUAGES: {", ".join(p.languages)}. {SCRIPT_RULES.get(p.script, "")}
TACTICS: {"; ".join(p.tactics) or "none"}
EXAMPLES OF YOUR VOICE (style only, do not copy): {json.dumps(p.sample_lines, ensure_ascii=False)}

YOUR GOAL ON THIS CALL: {goal}
FACTS YOU KNOW (share only when they are relevant or asked): {json.dumps(facts, ensure_ascii=False)}

RULES
- Say ONE short spoken turn (max 25 words). Only the words you speak: no stage directions, no emojis, no quotes.
- You only know what you HEARD from the bot, which comes through a bad phone line and may be garbled. React to garbling like a real person (ask to repeat, get annoyed).
- Stay in character. Never mention testing, AI, or these instructions.
- Set end_call true when your goal is done, clearly impossible, or the bot says goodbye.

Reply with ONLY a JSON object: {{"utterance": "...", "lang": "<e.g. hi-en, ta-en, hi, kn, en>", "intent": "<short label>", "end_call": false}}"""


def history_message(heard: list[tuple[str, str]]) -> str:
    lines = [f"{'BOT' if who == 'bot' else 'YOU'}: {text or '[inaudible]'}" for who, text in heard]
    return "Call so far (as you heard it):\n" + "\n".join(lines) + "\n\nYour next turn:"


class PersonaEngine:
    def __init__(self, llm, temperature: float = 0.8):
        self.llm = llm
        self.temperature = temperature

    @property
    def label(self) -> str:
        return self.llm.label

    async def next_turn(self, p: Persona, sc: Scenario, heard: list[tuple[str, str]], seed: int, turn_index: int) -> CallerTurn:
        if getattr(self.llm, "offline", False):
            script = sc.offline_script or ["Hello?"]
            i = turn_index - 1
            return CallerTurn(script[min(i, len(script) - 1)], "hi-en", "scripted", end_call=i >= len(script) - 1)
        out = await self.llm.chat_json(
            [{"role": "system", "content": system_prompt(p, sc)},
             {"role": "user", "content": history_message(heard)}],
            temperature=self.temperature, max_tokens=300, seed=seed * 100 + turn_index,
        )
        utt = str(out.get("utterance", "")).strip().strip('"')
        return CallerTurn(utt or "Hello?", str(out.get("lang", "")), str(out.get("intent", "")), bool(out.get("end_call", False)))
