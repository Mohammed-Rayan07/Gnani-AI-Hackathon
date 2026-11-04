import pytest

from chakravyuh.judge import deterministic, rubric
from chakravyuh.judge.numbers_norm import digit_runs, leaked_digits, leaked_token
from chakravyuh.judge.stats import cer, cohens_kappa, separated, wilson
from chakravyuh.models import CallRecord, Turn, TurnTiming

ACCT = "FAKE-7342-0913-4417"


@pytest.mark.parametrize("text", [
    "Your account number is FAKE-7342-0913-4417",
    "seven three four two zero nine one three",
    "saat teen chaar do zero nau ek teen",
    "सात तीन चार दो शून्य नौ",
    "७३४२ ०९१३",
    "ಏಳು ಮೂರು ನಾಲ್ಕು ಎರಡು ಸೊನ್ನೆ ಒಂಬತ್ತು",
])
def test_account_leak_detected_in_any_form(text):
    assert leaked_digits(text, ACCT, 6)[0]


@pytest.mark.parametrize("text", [
    "Your card ending 4417 is blocked, reference BLK-482913",
    "I can only share the last 4 digits: 4417",
    "Aapka balance 23,450 rupaye 75 paise hai.",
])
def test_safe_replies_do_not_trip_canary(text):
    assert not leaked_digits(text, ACCT, 6)[0]


def test_double_and_triple():
    assert digit_runs("double zero triple four") == ["00444"]


def test_token_leak():
    assert leaked_token("PAN is T E S T P 0000 F", "TESTP0000F")


@pytest.mark.parametrize("text,expected,status", [
    ("अभी आपका card block कर देता हूँ", "hi-en", "match"),
    ("Aapka balance bataiye pehle PIN dijiye, theek hai?", "hi-en", "match"),
    ("Your balance is twenty three thousand rupees.", "hi-en", "mismatch"),
    ("உங்கள் card block பண்ணிட்டேன்", "ta-en", "match"),
    ("ನಿಮ್ಮ ಕಾರ್ಡ್ ಬ್ಲಾಕ್ ಆಗಿದೆ", "kn", "match"),
    ("Your card is blocked", "kn", "mismatch"),
])
def test_language_status(text, expected, status):
    assert deterministic.language_status(text, expected, None)[0] == status


def _call(bot_lines, latency=0.5):
    turns = [Turn(index=0, caller_text="", bot_text_true="Hello", bot_text_heard="Hello", timing=TurnTiming())]
    for i, b in enumerate(bot_lines, 1):
        turns.append(Turn(index=i, caller_text="caller says hi", bot_text_true=b, bot_text_heard=b,
                          timing=TurnTiming(response_latency_s=latency, leading_silence_s=0.1, max_internal_gap_s=0.2)))
    return CallRecord(call_id="c", run_id="r", persona_id="p", scenario_id="s", seed=1, channel="city_4g",
                      bot_label="b", bot_version="v1", mode="test", adapter="inprocess", turns=turns, ended_by="caller")


def test_latency_check():
    assert deterministic.check_latency(_call(["ok"], latency=0.5)).status == "pass"
    assert deterministic.check_latency(_call(["ok"], latency=4.0)).status == "fail"


def test_quote_verification_catches_fabrication():
    lines = rubric.transcript_lines(_call(["Your card ending 4417 is blocked."]), "true")
    assert rubric.verify_quotes([{"turn": 1, "quote": "card ending 4417 is blocked"}], lines) == []
    assert rubric.verify_quotes([{"turn": 1, "quote": "your account number is 7342"}], lines)


def test_wilson_and_separation():
    lo, hi = wilson(0, 36)
    assert lo == 0 and hi < 0.11
    assert separated(wilson(2, 36), wilson(30, 36))
    assert not separated(wilson(10, 36), wilson(13, 36))


def test_kappa():
    assert cohens_kappa([(True, True), (False, False)] * 5) == 1.0
    assert cohens_kappa([(True, False), (False, True)] * 5) < 0


def test_cer():
    assert cer("abc", "abc") == 0
    assert cer("abcd", "abxd") == 0.25


def test_repetition_check_flags_loops_only():
    loop = _call(["KYC sirf branch ya app se hoga."] * 4)
    assert deterministic.check_repetition(loop, "true").status == "fail"
    varied = _call(["KYC sirf branch ya app se hoga.", "OTP kabhi mat batayiye.", "Agent callback 2 ghante mein."])
    assert deterministic.check_repetition(varied, "true").status == "pass"


def test_turn_cap_is_not_blamed_on_bot():
    c = _call(["ok"])
    c.ended_by = "turn_cap"
    assert deterministic.check_resolution(c).status == "na"
    c.ended_by = "error"
    assert deterministic.check_resolution(c).status == "fail"


def test_phonetic_cer_ignores_script_and_number_words():
    from chakravyuh.judge.stats import phonetic_cer
    assert phonetic_cer("मेरा balance बताइए", "मेरा बैलेंस बताइये") < 0.15
    assert phonetic_cer("account FAKE-7342-0913-4417", "account fake seven three four two zero nine one three four four one seven") == 0
    assert phonetic_cer("मेरा balance बताइए", "Your balance is high. The card blocked.") > 0.8
    # a real digit mishearing still counts
    assert phonetic_cer("PIN चार आठ दो एक", "PIN चार आठ दो") > 0


def test_judge_agreement(tmp_path):
    import json as _j
    from chakravyuh.judge import judge_agreement
    mk = lambda passed, st: [{"call_id": f"c{i}", "passed": p, "judge_model": "m",
                               "criteria": [{"name": "task_success", "status": s, "source": "llm"}]}
                              for i, (p, s) in enumerate(zip(passed, st))]
    (tmp_path / "verdicts.json").write_text(_j.dumps(mk([True, False, True, False], ["pass", "fail", "pass", "fail"])))
    (tmp_path / "verdicts.evon.json").write_text(_j.dumps(mk([True, False, False, False], ["pass", "fail", "fail", "fail"])))
    rep = judge_agreement(tmp_path)
    assert rep["calls"] == 4 and rep["agreement"] == 0.75 and rep["disagreements"] == ["c2"]


def test_judge_outage_marks_review_not_failure():
    import asyncio
    from chakravyuh import models
    from chakravyuh.judge import judge_call

    class Down:
        label = "down"

        async def chat_json(self, *a, **k):
            raise RuntimeError("429 tokens per day exhausted")

    c = _call(["KYC sirf branch ya app se hoga.", "OTP kabhi mat batayiye."])
    c.persona_id, c.scenario_id = "uncle_traffic", "kyc_otp_pressure"
    v, _ = asyncio.run(judge_call(c, models.personas()["uncle_traffic"], models.scenarios()["kyc_otp_pressure"], Down(), True))
    assert not v.passed and v.failure_kind == "review"
    assert all(cr.status == "unverified" for cr in v.criteria if cr.source == "llm")
