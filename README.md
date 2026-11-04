# CHAKRAVYUH

**Crash-test dummies for Indian voice bots.**

Synthetic Indian callers phone a voice bot over a simulated noisy 8 kHz phone line. For example: a Hinglish uncle shouting over traffic, a Tamil-English aunty, a farmer on a breaking 2G line, and a "bank officer" fishing for a (fake) OTP. Every failure comes back as **audio evidence** on a scorecard, with a v1→v2 regression diff.

Built on Gnani AI models:
- **Prisma** (speech-to-text) hears the bot through the bad line.
- **Timbre** (text-to-speech) voices the callers, and **Timbre voice cloning** makes one of them my own voice.
- **Evon** writes the callers and judges the calls.

> Built for the Gnani AI Great Indian AI Internship Challenge 2026. All callers, names and identifiers are synthetic.

---

## Why

Voice-bot demos run on a quiet laptop mic. Real Indian callers don't:
- they are on 8 kHz lines with traffic behind them, packet loss and cheap handsets;
- they switch Hindi→English mid-sentence and say numbers as "chaar aath do ek";
- some of them are social engineers.

Model benchmarks (WER on single clips) don't tell you whether **a deployed bot** survives a whole conversation like that. CHAKRAVYUH does.

## How a simulated turn works

```
persona LLM ──text──▶ Timbre / cloned voice ──16 kHz──▶ upstream line ─┐
   ▲                                                  (noise @ SNR, band-pass,
   │                                                   8 kHz, μ-law/opus, burst loss)
   │                                                                    ▼
 what the caller heard ◀── Prisma ◀── downstream line ◀── bot reply ◀── BOT UNDER TEST
                                                         │
                                         VAD timing on the bot's own audio
                                         (latency, dead air)

logged turns ──▶ deterministic checks (PII canaries, language, latency, completion)
             ──▶ LLM rubric with machine-verified quotes ──▶ scorecard.html / diff.html / crash reels
```

| Line profile | What it simulates |
|---|---|
| `clean_pstn` | Control: quiet room, G.711 μ-law, no loss |
| `city_4g` | Street traffic at 12 dB SNR, 1% bursty loss |
| `rural_2g` | Market babble + fan at 5 dB SNR, 8% bursty loss, low-bitrate opus, clipping |

## Quickstart

```bash
uv sync --extra dev                         # Python 3.12 (pinned), ffmpeg on PATH
cp .env.example .env                        # add GNANI_API_KEY + LLM endpoints
```

```bash
chakravyuh doctor                           # verifies .env, keys, Gnani TTS/STT (incl. 8 kHz) and all 3 LLMs
chakravyuh smoke                            # Timbre -> every line profile -> Prisma, prints CER per profile
```

```bash
chakravyuh run --bot inprocess:v1 --yes     # 4 callers x 3 scenarios x 3 seeds
chakravyuh run --bot inprocess:v2 --yes
chakravyuh judge runs/<v1-run>  &&  chakravyuh judge runs/<v2-run>
chakravyuh report runs/<v2-run>
chakravyuh diff runs/<v1-run> runs/<v2-run>
chakravyuh reel runs/<v1-run> <call_id>     # 15 s captioned crash reel (4:5, 9:16 or 16:9)
```

No key yet? `CHAKRAVYUH_OFFLINE=1` runs the whole pipeline with simulated speech. The results are stamped as meaningless dry-run output.

### Test your own bot

Expose this contract, then run `chakravyuh run --bot audio-http:http://localhost:8100/v1`:

```
POST /call/start              -> audio/wav (greeting), header X-Session-Id
POST /call/{sid}/turn         multipart "audio" (8 kHz wav) -> audio/wav
optional headers: X-End-Call: 1, X-Bot-Text (base64) to enable the harness-noise floor
```

A text-only bot can use `text-http:` instead. The harness then wraps it with Prisma and Timbre, and the scorecard is stamped *logic-only*. A ready-made CI gate is in [`examples/voice-regression-gate.yml`](examples/voice-regression-gate.yml).

Adversarial (social-engineering) callers only ever run against **your own** bot.

### Comment loop

```bash
chakravyuh caller "my nani who mixes Bhojpuri and Hindi and keeps asking about her pension"
```

This builds the persona, calls bot v2, judges the call and renders a reel. It also prints a ready-to-post reply that names the model that generated the caller.

- **Unsupported languages are mapped honestly.** Bhojpuri becomes Hindi with Bhojpuri words, and the reply says so.
- **Real numbers and IDs are refused.**

## Honesty rules (built into the code)

- **The bot is judged on what it actually said, wherever the bot exposes its reply text.** A failure that appears only in the noisy transcript is a *harness error*, reported in a separate noise-floor table. Noise that makes the *bot* mishear the *caller* still counts against the bot, as it would in real life.
- **Deterministic checks gate first.** PII canaries are caught in any spoken form: "saat teen chaar do", "सात तीन", "double zero", native digits.
- **LLM verdicts must quote the transcript verbatim, and every quote is checked by machine.** A verdict whose quotes can't be found is marked *unverified*, never counted as a pass.
- **The judge must be a different model from the bot.**
- **A scenario passes if at least 2 of its 3 seeds pass.** Call pass rates carry Wilson 95% intervals, and the diff only says "improved" when those intervals separate.
- **Judge agreement is published.** `chakravyuh label` collects blind hand labels and `chakravyuh kappa` reports Cohen's κ against them.
- **Barge-in is shown as N/A.** The harness runs a turn-based REST loop.
- **All identifiers are visibly fake** (`FAKE-7342-0913-4417`, `TESTP0000F`, `00000-41779`), and `chakravyuh lint` fails on anything that looks real.

## Reference bot "Dhan Seva" (fictional bank)

- **v1 = realistic first draft.** It has an English-only prompt, the CRM record pasted in, product facts but no security policy, and verbose turns.
- **v2 = hardened.** It mirrors the caller's language mix, keeps phone-length turns, follows PII/OTP rules, confirms numbers back, and asks the caller to repeat on garbled input.

Both prompts are in [`refbot/`](refbot/), so anyone can rerun the diff.

## Results

_To be filled from `runs/*/summary.json` after the live runs; nothing here is estimated._

| | v1 | v2 |
|---|---|---|
| Scenarios passed (≥2/3 seeds) | – | – |
| Call pass rate (95% CI) | – | – |
| Calls leaking a fake identifier | – | – |
| p50 / p90 time to first word | – | – |
| Judge vs human κ (n=35) | – | – |

## Models used

| Job | Model |
|---|---|
| Caller speech | Gnani Timbre v2.5 + `vachana-vc-v1` voice clone (my own voice, see [CONSENT](docs/CONSENT.md)) |
| Hearing the bot through the line | Gnani Prisma v3.0 (`indic-auto`, `codemix`) |
| Caller personas, comment-loop callers, judge | Gnani Evon v3.3 where a GPU window was available; otherwise the fallback model named in each run's manifest |
| Reference bot brain | named in each run's manifest |

## Limitations

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).
- The phone line is simulated, not a carrier network.
- Language matching is approximate.
- An LLM judge is not ground truth, which is why κ is published.

## Cost

Every Gnani call goes through a credit ledger with a hard cap (`CREDIT_CAP`). A pre-flight estimate requires `--yes` above `CONFIRM_ABOVE`. `chakravyuh budget` shows the spend so far. Cache hits are free.

## License

Apache-2.0.
