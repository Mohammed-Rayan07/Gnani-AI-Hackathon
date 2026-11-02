import pytest

from chakravyuh import safety
from chakravyuh.caller_gen import language_mapping


def test_repo_data_is_synthetic():
    assert safety.lint_repo_data() == []


@pytest.mark.parametrize("text", ["call me on 9876543210", "aadhaar 2345 6789 0123", "PAN ABCDE1234F", "x@y.com"])
def test_real_pii_rejected(text):
    assert safety.find_problems(text)


@pytest.mark.parametrize("text", ["FAKE-7342-0913-4417", "TESTP0000F", "00000-41779", "BLK-482913"])
def test_fake_ids_allowed(text):
    assert safety.find_problems(text) == []


def test_unsupported_language_mapped_honestly():
    codes, note = language_mapping("my nani who mixes Bhojpuri and Hindi")
    assert codes[0] == "hi"
    assert "Bhojpuri isn't supported" in note


def test_odia_maps_to_bengali():
    codes, note = language_mapping("an Odia grandmother")
    assert codes == ["bn"] and "Odia" in note
