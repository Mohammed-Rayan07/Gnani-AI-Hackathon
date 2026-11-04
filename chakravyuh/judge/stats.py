"""Statistical honesty: Wilson intervals, Cohen's kappa, CER."""

from __future__ import annotations

import math
import re
import unicodedata


def wilson(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = passes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def separated(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[1] < b[0] or b[1] < a[0]


def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    agree = sum(a == b for a, b in pairs) / n
    pa = sum(a for a, _ in pairs) / n
    pb = sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe == 1.0:
        return 1.0 if agree == 1.0 else 0.0
    return (agree - pe) / (1 - pe)


def _norm_chars(s: str) -> str:
    s = unicodedata.normalize("NFC", s).casefold()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def cer(reference: str, hypothesis: str) -> float | None:
    r, h = _norm_chars(reference), _norm_chars(hypothesis)
    if not r:
        return None
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[-1] / len(r)


# ----------------------------------------------------------------------------- script-neutral CER
# Prisma writes English loanwords in Devanagari ("बैलेंस" for "balance") and digits as words
# ("seven three" for "73"). Raw CER counts both as errors. phonetic_cer() maps every side to a
# consonant skeleton in Latin (numbers -> digits, vowels dropped, voiced/unvoiced pairs merged),
# so it measures mishearing rather than spelling. It is a coarse metric; both are reported.

_DEVA = dict(zip("कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहळ",
                 ["k", "k", "g", "g", "n", "c", "c", "j", "j", "n", "t", "t", "d", "d", "n", "t", "t", "d", "d", "n",
                  "p", "f", "b", "b", "m", "y", "r", "l", "v", "s", "s", "s", "h", "l"]))
_DEVA.update({"क़": "k", "ख़": "k", "ग़": "g", "ज़": "j", "ड़": "r", "ढ़": "r", "फ़": "f", "ं": "n", "ँ": "n"})
_TAMIL = dict(zip("கஙசஞடணதநபமயரலவழளறனஜஷஸஹ",
                  ["k", "n", "c", "n", "t", "n", "t", "n", "p", "m", "y", "r", "l", "v", "l", "l", "r", "n", "j", "s", "s", "h"]))
_KANNADA = dict(zip("ಕಖಗಘಙಚಛಜಝಞಟಠಡಢಣತಥದಧನಪಫಬಭಮಯರಲವಶಷಸಹಳ",
                    ["k", "k", "g", "g", "n", "c", "c", "j", "j", "n", "t", "t", "d", "d", "n", "t", "t", "d", "d", "n",
                     "p", "f", "b", "b", "m", "y", "r", "l", "v", "s", "s", "s", "h", "l"]))
_KANNADA["ಂ"] = "n"
_INDIC = {**_DEVA, **_TAMIL, **_KANNADA}
_LATIN_DIGRAPHS = [("ch", "c"), ("sh", "s"), ("ph", "f"), ("th", "t"), ("dh", "d"), ("kh", "k"), ("gh", "g"),
                   ("bh", "b"), ("jh", "j"), ("ck", "k"), ("qu", "kv"), ("x", "ks"), ("q", "k"), ("w", "v"), ("z", "j")]
_MERGE = str.maketrans({"g": "k", "j": "c", "d": "t", "b": "p"})


def _latin_skeleton(word: str) -> str:
    for a, b in _LATIN_DIGRAPHS:
        word = word.replace(a, b)
    word = re.sub(r"c(?=[eiy])", "s", word).replace("c", "k") if "c" in word and not re.search(r"[^a-z]", word) else word
    return re.sub(r"[aeiouyh]", "", word)


def phonetic_skeleton(text: str) -> str:
    from .numbers_norm import WORD_DIGITS, native_digits_to_ascii

    text = native_digits_to_ascii(unicodedata.normalize("NFC", text)).casefold()
    words: list[str] = []
    digits = ""                                   # consecutive digits/number words join into one run
    for tok in re.findall(r"[^\s.,!?।:;\"'()\-/]+", text):
        d = WORD_DIGITS.get(tok) or (tok if tok.isdigit() else None)
        if d is not None:
            digits += d
            continue
        if digits:
            words.append(digits)
            digits = ""
        if re.fullmatch(r"[a-z]+", tok):
            sk = _latin_skeleton(tok)
        else:
            # Indic word: consonants only (vowel signs, viramas and independent vowels are dropped)
            sk = "".join(ch if "a" <= ch <= "z" else _INDIC.get(ch, "") for ch in tok)
        sk = re.sub(r"([a-z])\1+", r"\1", sk.translate(_MERGE))   # collapse doubled consonants
        if sk:
            words.append(sk)
    if digits:
        words.append(digits)
    return " ".join(words)


def phonetic_cer(reference: str, hypothesis: str) -> float | None:
    r = phonetic_skeleton(reference)
    if not r.replace(" ", ""):
        return None
    return cer(r, phonetic_skeleton(hypothesis))
