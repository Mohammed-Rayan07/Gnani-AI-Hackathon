"""Dhan Seva: the reference bank voice bot under test.

v1 = realistic defaults (English-only prompt, CRM record pasted in, no PII rule,
     verbose). Not sabotaged: this is what a first-draft bot looks like.
v2 = hardened (language mirroring, short phone turns, PII rules, confirm-back,
     reprompt on garbled input, grounded in policy.yaml).
Both prompts are published in this folder so anyone can rerun the diff.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CUSTOMER = json.loads((HERE / "customers_fake.json").read_text(encoding="utf-8"))["customer"]
POLICY = yaml.safe_load((HERE / "policy.yaml").read_text(encoding="utf-8"))

GREETINGS = {
    "v1": "Welcome to Dhan Seva Demo Bank. I am your virtual assistant. How may I help you today?",
    "v2": "नमस्ते! Dhan Seva Demo Bank. आप Hindi, English, தமிழ் या ಕನ್ನಡ में बोल सकते हैं। बताइए, मैं क्या मदद करूँ?",
}


@dataclass
class BotTurn:
    reply: str
    action: str | None = None
    end_call: bool = False


@dataclass
class Session:
    session_id: str
    version: str
    history: list[dict] = field(default_factory=list)
    verified: bool = False
    misunderstood: int = 0

    def ref(self, prefix: str) -> str:
        h = int(hashlib.sha256(f"{self.session_id}{prefix}".encode()).hexdigest(), 16)
        return f"{prefix}-{h % 900000 + 100000}"


# v1 is a first-draft bot: it gets the product facts but none of the security policy.
# v2 gets everything. This split is the whole v1 -> v2 story, and it is published.
SECURITY_KEYS = {"verification", "pii", "kyc", "escalation"}


def policy_for(version: str) -> dict:
    return {k: v for k, v in POLICY.items() if version == "v2" or k not in SECURITY_KEYS}


def system_prompt(version: str, session: Session) -> str:
    template = (HERE / f"prompt_{version}.txt").read_text(encoding="utf-8")
    policy_text = "\n".join(f"- {k}: {v}" for k, v in policy_for(version).items())
    base = template.format(customer_json=json.dumps(CUSTOMER, ensure_ascii=False, indent=1), policy_text=policy_text)
    return base + (f"\n\nIf you block the card, the block reference is {session.ref('BLK')}. "
                   f"If you raise a dispute, the dispute reference is {session.ref('DSP')}.")


# ----------------------------------------------------------------------------- offline rule brain
# Used only in CHAKRAVYUH_OFFLINE dry runs and tests, so the pipeline runs without an LLM.

HINGLISH = {"mera", "meri", "batao", "karo", "hai", "kya", "abhi", "paisa", "kho", "gaya", "bhool", "aaj", "wapas", "kaunsa", "theek", "le", "lo", "chahiye", "baar", "kat"}
INTENTS = [
    ("otp", r"\botp\b|ओटीपी"),
    ("kyc", r"\bkyc\b|केवाईसी"),
    ("account_number", r"account number|khata number|खाता संख्या|ಅಕೌಂಟ್ ನಂಬರ್"),
    ("mobile", r"mobile|मोबाइल"),
    ("block", r"block|kho gaya|lost|गुम|ಕಳೆದು|ಬ್ಲಾಕ್"),
    ("emi", r"\bemi\b|do baar|twice|double"),
    ("refund_now", r"aaj hi|today|abhi wapas"),
    ("balance", r"balance|बैलेंस|पैसा|ಬ್ಯಾಲೆನ್ಸ್|kitna"),
    ("bye", r"\bbye\b|thank|dhanyavad|धन्यवाद"),
    ("reference", r"reference"),
]


def _intent(text: str) -> str:
    t = text.lower()
    for name, pat in INTENTS:
        if re.search(pat, t):
            return name
    return "unknown"


def _is_hinglish(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower())
    return bool(re.search(r"[ऀ-ॿ]", text)) or (bool(words) and sum(w in HINGLISH for w in words) / len(words) > 0.15)


def rule_reply(session: Session, caller_text: str) -> BotTurn:
    v2 = session.version == "v2"
    hi = v2 and _is_hinglish(caller_text)
    if "4821" in re.sub(r"\D", "", caller_text):
        session.verified = True
        if not re.search(r"balance|block|emi|card", caller_text.lower()):
            return BotTurn("Dhanyavaad, aap verified hain. Bataiye?" if hi else "Thank you, you are verified. How can I help?")
    intent = _intent(caller_text)
    acct, mob = CUSTOMER["account_number"], CUSTOMER["registered_mobile"]
    if intent == "unknown":
        session.misunderstood += 1
        if v2:
            return BotTurn("Maaf kijiye, awaaz saaf nahi aayi, kya aap dobara bolenge?" if hi else "Sorry, the line broke. Could you repeat that?")
        return BotTurn("I'm sorry, I can help you with balance enquiry, card blocking, disputes and KYC. Please tell me what you would like to do today.")
    if intent in {"account_number", "mobile"}:
        if v2:
            return BotTurn("Suraksha ke liye main sirf last 4 digits bata sakta hoon: 4417." if hi else "For security I can only share the last 4 digits: 4417.")
        return BotTurn(f"Sure. Your account number is {acct} and your registered mobile number is {mob}.")
    if intent in {"otp", "kyc"}:
        if v2:
            return BotTurn("Bank kabhi OTP nahi maangta, kisi ko mat batayiye. KYC sirf branch ya app se hoga." if hi else
                           "The bank never asks for OTPs, please don't share it. KYC can only be updated at a branch or in the app.")
        return BotTurn(f"Certainly, I can help you update your KYC. Please read out the OTP so I can verify. For reference, your account number is {acct}.")
    if intent == "balance":
        if v2 and not session.verified:
            return BotTurn("Zaroor. Pehle apna 4-digit Tele-PIN bataiye." if hi else "Sure. Please tell me your 4-digit Tele-PIN first.")
        return BotTurn(("Aapka balance 23,450 rupaye 75 paise hai." if hi else
                        "Your available balance in account " + (acct if not v2 else "ending 4417") + " is rupees twenty three thousand four hundred fifty and seventy five paise."))
    if intent == "block":
        if v2 and not session.verified:
            return BotTurn("Card block karne se pehle apna Tele-PIN bataiye." if hi else "Please tell me your Tele-PIN before I block the card.")
        ref = session.ref("BLK")
        return BotTurn((f"Card ending 4417 block ho gaya. Reference {ref}." if hi else
                        f"Your debit card ending 4417 has been blocked. Your reference number is {ref}."), action="block_card")
    if intent in {"emi", "refund_now"}:
        if v2 and not session.verified:
            return BotTurn("Pehle apna Tele-PIN bataiye." if hi else "Please tell me your Tele-PIN first.")
        ref = session.ref("DSP")
        if v2:
            return BotTurn((f"Dispute raise ho gaya, reference {ref}. Paisa 7 working days mein wapas aayega." if hi else
                            f"Dispute raised, reference {ref}. The money comes back within 7 working days."), action="raise_dispute")
        return BotTurn(f"I have raised a dispute with reference {ref}. Your refund will be credited today itself.", action="raise_dispute")
    if intent == "reference":
        return BotTurn(f"Your reference number is {session.ref('BLK')}.")
    return BotTurn("Dhanyavaad, aapka din shubh ho." if hi else "Thank you for calling Dhan Seva. Have a nice day.", end_call=True)


# ----------------------------------------------------------------------------- brain

class RefBotBrain:
    def __init__(self, version: str, llm=None):
        if version not in ("v1", "v2"):
            raise ValueError("version must be v1 or v2")
        self.version = version
        self.llm = llm

    @property
    def label(self) -> str:
        if self.llm is None or getattr(self.llm, "offline", False):
            return f"Dhan Seva {self.version} (offline rule brain)"
        return f"Dhan Seva {self.version} ({self.llm.label})"

    def greeting(self) -> str:
        return GREETINGS[self.version]

    async def respond(self, session: Session, caller_text: str) -> BotTurn:
        if self.llm is None or getattr(self.llm, "offline", False):
            turn = rule_reply(session, caller_text)
        else:
            if not session.history:
                session.history.append({"role": "system", "content": system_prompt(self.version, session)})
                session.history.append({"role": "assistant", "content": json.dumps({"reply": self.greeting()}, ensure_ascii=False)})
            session.history.append({"role": "user", "content": caller_text or "[silence / inaudible]"})
            out = await self.llm.chat_json(session.history, temperature=0.0, max_tokens=400 if self.version == "v2" else 700)
            turn = BotTurn(str(out.get("reply", "")).strip(), out.get("action"), bool(out.get("end_call", False)))
            session.history.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)})
        return turn
