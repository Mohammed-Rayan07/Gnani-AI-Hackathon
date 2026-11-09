# CHAKRAVYUH: solution pitch

**Crash-test dummies for Indian voice bots.** Mohammed Rayan (solo) · NITK Surathkal · Great Indian AI Internship Challenge 2026

## The problem
Indian voice bots get tested on clean audio, by people speaking clean English or Hindi. Their real callers ring from traffic and from 2G villages, switch between Hindi and English mid-sentence, and some are social engineers fishing for an OTP. Teams find these failures from customers, after launch. There's no simple, repeatable way to test a voice bot the way it will actually be called.

## The solution
CHAKRAVYUH phones a voice bot with synthetic Indian callers over a simulated phone line, judges every call, and returns each failure with proof.

1. **A caller writes a line.** An LLM plays a persona (an impatient Hinglish uncle, a Tamil aunty, a farmer on 2G, a Kannada auto driver, a fake "bank officer") and only knows what it heard.
2. **Gnani Timbre speaks it.** One caller is my own voice, cloned with Gnani voice cloning (with recorded consent).
3. **The phone line.** Noise at a set SNR, a 300–3400 Hz band, 8 kHz, a μ-law or Opus codec and bursty packet loss.
4. **The bot answers,** over HTTP, so any voice bot can be tested.
5. **Gnani Prisma hears the reply** through the same bad line.
6. **The judge scores it.** Code checks for leaked IDs, language, dead air and repetition come first and can't be overruled. An LLM judge then scores task, policy and social-engineering resistance, and every quote it gives is machine-checked against the transcript.

## What makes it different
- **Audio evidence, not just a score.** Every failure shows the turn, the exact quote and the audio as the caller heard it.
- **Line vs bot.** Failures caused by the phone line are labelled separately, using a script-neutral error rate, so the bot isn't blamed for noise.
- **Leaks caught however they're spoken.** Numbers are matched in English, Hindi, Tamil and Kannada words.
- **Honest statistics.** 3 seeds per cell and Wilson 95% intervals; "improved" only when the intervals separate.
- **Regression-ready.** The output is a v1→v2 diff, a dashboard and captioned crash reels, with a CI gate example for other bots.

## Found on live calls
- Version 1 of my reference bank bot read a full (fake) account number to an unverified caller on turn one.
- Version 2 never leaked, but the judge caught it repeating the same refusal eight times under pressure.
- On a 2G-quality line, a Hindi "tell me my balance, block my card" came back from speech-to-text as "Your balance is high. The card blocked."

## Built with
**Gnani:** Timbre v2.5 TTS, Timbre voice cloning (`vachana-vc-v1`), Prisma v3.0 STT (`indic-auto`, `codemix`, 8 kHz).
**Other:** open-weight LLMs on Groq for the callers, the reference bot and the judge (the judge is always a different model from the bot). Python, FastAPI, ffmpeg. All data is synthetic and visibly fake.

## Who it's for, and what's next
Voice-bot teams at Indian banks, telecom, insurance and support centres, who need a test before every release. Next: more languages and dialects, real-time streaming with barge-in, Evon v3.3 as a second judge, and callers designed from public comments.
