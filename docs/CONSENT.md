# Consent and data

## Cloned voice
The only cloned voice in this project is the author's own.

- Sample: ~22 s of my own speech, recorded on 9 November 2026 specifically for this project.
- Statement recorded at the start of the sample: "I, Mohammed Rayan, consent to cloning my voice with Gnani Timbre for the CHAKRAVYUH project."
- The embedding (`voices/me.json`) is gitignored and never published.
- `chakravyuh clone-voice` refuses to run without `--i-consent`.

No other person's voice is cloned or recorded. Comment-loop callers always use stock Timbre voices.

## Synthetic data only
- Every name, account, card, mobile, PAN and OTP is fictional and visibly fake (`FAKE-`, `TEST`, `00000-` prefixes).
- `chakravyuh lint` (run in CI) fails on anything that looks like a real Indian mobile, Aadhaar, PAN, card or email.
- No real calls, recordings or customer data are used anywhere.
- Noise beds are synthetic, or CC0 recordings listed in `assets/noise/LICENSES.md`, with no bystander speech.

## Adversarial callers
The social-engineering persona is a **PII-leak test for your own bot**. The harness refuses to run it against any bot except the in-process reference bot. Crash tests of other people's bots happen only with the owner's consent, and only with non-adversarial personas.
