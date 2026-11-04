# CLAUDE.md: project memory for CHAKRAVYUH

Read this first, every session. It is the full technical context handed over from the cloud build session (Nov 2–5, 2026). User-facing explanations live in the private `STUDY_GUIDE.md` (gitignored; the user keeps a copy).

## 1. What this is
**CHAKRAVYUH: crash-test dummies for Indian voice bots.** Synthetic Indian callers (LLM persona → Gnani **Timbre** TTS, one caller in the user's own **cloned voice**) phone a voice bot over a **simulated noisy 8 kHz phone line**. Gnani **Prisma** STT hears the bot through the same line. A judge (deterministic checks + LLM rubric with machine-verified quotes) scores every call. The outputs are a scorecard with failure audio, a v1→v2 diff, crash reels, a public site and a 60-second demo video.

- **Context:** built for the Gnani AI *Great Indian AI Internship Challenge 2026* (gnani.ai/internship).
- **Deadline:** **10 Nov 2026, 11:59 PM IST**.
- **Selection:** by verified LinkedIn/X engagement on nominated posts (needs #GreatIndianAIInternshipChallenge #GnaniAI and a Gnani tag), then individual interviews.
- **Awards:** max **one** award per entrant. The target is **Noise Canceller** (noisy telephonic audio); backups are Solo Ninja and Demo Day Drop.
- **Entrant:** solo.

## 2. Hard rules (never break)
1. **Never print, log, paste or commit secrets.** `.env` holds `GNANI_API_KEY`, Groq/Gemini keys (the user named them `Groq_API_KEY`, `Gemini_API_KEY` and copied them into the role vars). Show `.env` by variable names only.
2. **Never commit** `.env`, `runs/`, `.cache/`, `voices/*.json|*.wav`, `launch/`, `STUDY_GUIDE.md`, `me.wav`, `rec.m4a`. Run `git status` before every commit.
3. **Synthetic data only** (a competition rule, and the DPDP Act covers voice). Identifiers are visibly fake: `FAKE-7342-0913-4417`, `00000-41779`, `TESTP0000F`, Tele-PIN `4821`, OTP `000913`. `chakravyuh lint` (in CI) rejects real-looking mobiles, Aadhaar, PAN, cards and emails.
4. **Never fake or estimate a result.** Every public number comes from judged runs (`summary.json` / `verdicts.json`). Offline (`CHAKRAVYUH_OFFLINE=1`) numbers are meaningless and are bannered; they must never reach README/RESULTS (the code enforces this).
5. **The judge model must differ from the bot model** (`_check_judge_differs`).
6. **Adversarial personas** (`social_engineer`) run only against the in-process reference bot, never a third-party bot.
7. **Clone only the user's own voice**, with `--i-consent` and `docs/CONSENT.md` filled in.
8. **Don't weaken tests or checks** to make things pass.
9. Commit messages end with the attribution lines the harness gives. No model IDs in commits or code.

## 3. Environment
- **User machine:** Windows laptop, PowerShell, 16 GB RAM, RTX 4050 6 GB.
- **Repo:** `C:\Users\rayan\OneDrive\Desktop\Claude Code\Gnani-AI-Hackathon`. Always `cd` there; the user once ran git in the wrong folder.
- **Branch:** `claude/keen-knuth-0h4b9r` (all work). The remote is `github.com/Mohammed-Rayan07/Gnani-AI-Hackathon` (private until launch).
- **Python 3.12**, pinned via `.python-version`, `requires-python <3.14` and `uv.lock`. uv once picked a pre-release 3.15 with no PyYAML wheel (it needed MSVC). Install with `uv sync --extra dev`; run via `uv run chakravyuh ...`.
- **ffmpeg** must be on PATH (opus codec, reels, video, libass captions). Use the Windows reel font `CHAKRAVYUH_REEL_FONT="Nirmala UI"` (covers Devanagari, Tamil and Kannada).
- The **cloud session** could not reach `api.vachana.ai`, Groq or huggingface (network policy), so live calls only run on the laptop.
- Windows consoles are cp1252; the CLI forces UTF-8 output (fixed in `3d6c16d`).
- **The repo is inside OneDrive.** A full launch writes about 2,000 WAVs plus cache files, and OneDrive sync can lock files mid-write. **Pause OneDrive syncing during `launch`** (tray icon → Pause syncing → 24 hours). If you see `PermissionError`/`WinError 32`, that's the cause: pause syncing and re-run (the run resumes).

## 4. Commands
```
uv run pytest -q                                   # 63 tests, ~3 min (test_launch: offline launch; test_live_paths: real clients vs mock APIs)
uv run chakravyuh doctor                           # .env, keys (masked), network, Timbre, Prisma 16k + 8k line, 3 LLMs
uv run chakravyuh smoke                            # one line through every channel profile, raw + phonetic CER
uv run chakravyuh launch --clone me.wav --i-consent --yes --publish    # EVERYTHING, resumable
uv run chakravyuh launch --steps results,kit,video --publish           # rebuild outputs only
uv run chakravyuh run --bot inprocess:v1 --personas uncle_traffic --scenarios kyc_otp_pressure --seeds 1 --max-turns 6 --yes
uv run chakravyuh judge runs/<run> [--judge evon] [--no-llm]
uv run chakravyuh report runs/<run> ; chakravyuh diff runs/<v1> runs/<v2>
uv run chakravyuh agree runs/<run>                 # kappa primary judge vs Evon
uv run chakravyuh label runs/<run> ; chakravyuh kappa runs/<run>        # judge vs human
uv run chakravyuh reel runs/<run> <call_id> --aspect 4:5|9:16|16:9
uv run chakravyuh caller "<comment text>"          # comment loop: persona -> call v2 -> judge -> reel -> reply text
uv run chakravyuh site <v1-run> <v2-run> [caller-runs...] --out site
uv run chakravyuh clone-voice me.wav --name me --i-consent
uv run chakravyuh lint ; chakravyuh budget
```
Offline dry run: `CHAKRAVYUH_OFFLINE=1` (fake STT/TTS, scripted callers, rule-based bot).

## 5. Architecture (module map)
```
chakravyuh/
  config.py         Settings from env/.env; LLMRole(persona|bot|judge|evon); ROOT; mode_label
  audio.py          float32 mono helpers, resample (resample_poly), wav io
  channel.py        PHONE LINE: noise@SNR -> 300-3400 Hz band-pass -> 8 kHz -> AGC/soft-clip -> mu-law|opus8k (ffmpeg)
                    -> Gilbert-Elliott burst loss on 20 ms frames (naive PLC). Seeded. degrade(x, sr, profile, seed, ambient)
  vad.py            energy VAD on the BOT'S OWN audio (latency/dead air; Prisma has no timestamps); split_for_stt (<=28 s)
  models.py         pydantic: Persona, Scenario(+Canary), Turn, TurnTiming, CallRecord, CriterionResult, CallVerdict
  persona_engine.py caller LLM: sees only what it HEARD; JSON {utterance, lang, intent, end_call}; hang-up + no-repeat rules
  orchestrator.py   run_call: greeting -> [persona -> TTS -> upstream line -> bot -> VAD -> downstream line -> Prisma] x N
                    run_matrix (Semaphore); estimate_cost; call_id = persona__scenario__s{seed}__{channel}
  clients/          prisma.py (REST /stt/v3), timbre.py (TTS + clone), llm.py (OpenAI-compatible, adaptive),
                    _http.py (retry, 429 Retry-After, up to 8 waits), offline.py (fakes), __init__.build_clients
  adapters/         inprocess.InProcessRefBot; http.AudioHTTPBot (wav contract), http.TextHTTPBot (wrapped = "logic-only")
  judge/            deterministic.py, rubric.py (LLM + quote verification), numbers_norm.py, stats.py (wilson, kappa,
                    cer, phonetic_cer), calibrate.py (label/kappa), __init__ (judge_call, summarize, judge_run, judge_agreement)
  report/           scorecard + diff + site_index Jinja2 templates (_base: CSS tokens, light/dark)
  reel.py           captioned crash reel (ASS via libass; colours are &HAABBGGRR = BGR!)
  video.py          60 s demo assembler (hook reel + cards + VO via Timbre; clone:me if present)
  launch.py         one-command pipeline helpers: build_specs, run_version (resumable), pick_reels, facts, results, kit
  site.py           static site: copies only referenced audio + reels; .nojekyll
  caller_gen.py     comment loop; unsupported-language mapping (Bhojpuri->hi, Odia/Assamese->bn, Tulu->kn, ...)
  safety.py         PII lint + assets/blocklist.txt
  doctor.py         setup checks with fix hints
  voices.py         Timbre v2.5 catalogue (one preferred language per voice) + refbot per-language voices
  cli.py            Typer app (all commands above)
refbot/             Dhan Seva fictional bank bot: brain.py (LLM or offline rule brain), pipeline.py (Prisma+LLM+Timbre),
                    app.py (FastAPI: /{v}/call/start|turn|end, /{v}/text/start|turn), prompt_v1.txt, prompt_v2.txt,
                    policy.yaml, customers_fake.json
personas/ scenarios/  YAML data; tests/  61 tests; docs/  RESULTS (generated), LIMITATIONS, CONSENT, RUNBOOK, LIVE_STATUS, EVON_LOCAL
.github/workflows/  ci.yml (lint + pytest), pages.yml (deploys site/ on push to site/** or manual dispatch)
examples/voice-regression-gate.yml   CI gate for other bots (audio-http contract)
```

### Run folder layout
```
runs/<run>/manifest.json            bot, models per role, mode, personas, scenarios, seeds, max_turns, llm_usage
runs/<run>/calls/<call_id>/call.json  CallRecord (turns: caller_text, bot_text_true, bot_text_heard, bot_heard_caller,
                                    bot_detected_lang, timing, channel_meta, audio paths)
runs/<run>/calls/<call_id>/tNN_caller_clean.wav | tNN_caller_line.wav (8k) | tNN_bot_raw.wav | tNN_bot_line.wav (8k)
runs/<run>/verdicts.json, summary.json        primary judge
runs/<run>/verdicts.evon.json, summary.evon.json, agreement.primary.evon.json   Evon second judge
runs/<run>/labels.jsonl, kappa.json           human labels
runs/<run>/scorecard.html, diff.html, reels/*.mp4
runs/launch-v1, runs/launch-v2      fixed folders used by `launch` (resumable)
runs/caller-*                       comment-loop runs (included in the site)
.cache/ledger.sqlite + content-hash caches (tts/stt/llm)
```

## 6. Gnani API: facts verified live on 2026-11-05 (docs/LIVE_STATUS.md)
- Base `https://api.vachana.ai`, header `X-API-Key-ID`. Some accounts allow **one active request at a time**: 429 `RATE_LIMITED` with no Retry-After (handled by backoff).
- **Prisma STT REST:** `POST /stt/v3`, multipart `audio_file`, `model=prisma-v3.0`, `language_code=indic-auto`, `format=codemix` (also `verbatim|transcribe|transliterate`). Clips must be 30 s or less. **8 kHz uploads are accepted.** The response has `transcript`, `request_id` and the detected language. There are no word timestamps, no diarization and no partials. WS `wss://api.vachana.ai/stt/v3/stream` exists, but it's real-time only and capped, so we don't use it.
- **Timbre TTS:** `POST /api/v1/tts/inference`, JSON `{text, voice, model:"timbre-v2.5", language, audio_config:{sample_rate, encoding:"linear_pcm", num_channels:1, sample_width:2, container:"wav"}}`. `language` is required for normal TTS. Each v2.5 voice has one preferred language (`voices.py`). `Shubhra` is NOT a v2.5 voice. v2.0 is deprecated. v3.0 has 13 all-language voices that aren't interchangeable with v2.5.
- **Voice clone:** `POST /api/v1/tts/voice-clone/embeddings`, multipart `audio_file`, 5–30 s. The response holds `data.voice_clone_embedding = {"embedding": "<string>", "shape": [1,768], "dtype": "torch.bfloat16"}`. Synthesize with `model:"vachana-vc-v1"` plus `speaker_embedding: <that whole object>`, **without** `language`. The format is from the docs and unit-tested, but it is **not yet tested live**, because no voice sample existed.
- **Timbre voices used:**
  - Callers: uncle `clone:me`, falling back to Jalaj (hi, male); farmer Vikrant; social_engineer Hemraj; tamil_aunty Noopur (ta); kannada_auto Kavin (kn); doctor/smoke Deepak.
  - Refbot, per reply language: Kaveri (en), Ambuja (hi), Vedika (ta), Saanvi (kn), Kirra (bn), Varuni (te).
  - The v1 bot always speaks with `en-IN`/Kaveri by design (the first-draft flaw).
- **Script test:** write Hinglish as **Devanagari Hindi with English words in Latin script**. Timbre pronounces both mixed and romanised input fine, but only mixed-script input survives a `codemix` round trip (CER 0.00–0.03 vs about 0.5). This was tested in Hindi only.
- **Smoke result:** on `rural_2g`, Prisma switched to English and paraphrased the sentence ("Your balance is high…"). That's a real 2G finding; label 2G failures carefully as harness or bot. सात→साथ (a digit lost) was the only real word error on the clean and 4G lines.
- **Evon v3.3:** `gnani/gnani-evon-v3.3-30B-A3B`, public (not gated), Apache-2.0, `nemotron_h` architecture, MoE with about 3B active, 128K context. **Not on the credits API.** A community GGUF exists at `luminenio/gnani-evon-v3.3-30B-A3B-GGUF`. On the laptop, use Q3_K_M or IQ4_XS through Ollama or llama.cpp (`docs/EVON_LOCAL.md`). It's used only as an optional second judge.
- **Credits:** 5,000. Third-party rate guesses: STT ₹0.5/min, TTS ₹2.8 per 1k chars (`RATE_*` in `.env`). Real rates are on the app.gnani.ai usage page (not read yet). The first live session spent about 17 by ledger estimate. A full launch is estimated at 460 or less.

## 7. LLM roles (.env `PERSONA_|BOT_|JUDGE_|EVON_LLM_BASE_URL/_MODEL/_API_KEY/_EXTRA_BODY/_JSON_MODE`)
- **Live setup (Groq, `https://api.groq.com/openai/v1`):** persona `openai/gpt-oss-20b`, bot `qwen/qwen3.8-27b`, judge `openai/gpt-oss-120b`.
- **Gemini was dropped.** The free tier allows 20 requests a day per model, `gemini-2.5-flash` returns 404 for new users, and the newer ones returned 503s.
- **Groq free tier** allows about 8k tokens a minute per model, so runs are slow but fine at `CONCURRENCY=2`. Daily token caps may stop a long run; `launch` resumes.
- **`LLMClient._post_adaptive`:**
  - drops `response_format`/`seed` if rejected;
  - retries `finish_reason=length` with 4× tokens (thinking models);
  - strips `<think>` and fences;
  - caches temp-0 and seeded requests by content hash;
  - counts `usage` (printed per run and stored in `manifest.llm_usage`).

## 8. Judge design (the part interviewers probe)
- **Views:**
  - **true** = what the bot really said (our refbot exposes it; HTTP bots can send `X-Bot-Text`);
  - **heard** = Prisma's transcript of the bot through the downstream line.
  - The LLM rubric runs **once, on the primary view** (true if available). The heard view gets deterministic checks only, which halves the judge tokens.
  - `failure_kind`: `harness` = passes on true but fails on heard (our STT misheard; not blamed on the bot). `bot`, `review` = only unverified LLM verdicts, or the judge was unavailable.
- **Deterministic checks:**
  - `pii_leak`: canary digits after normalising En/Hi/Ta/Kn number words, double/triple and native digits; a match is 6 or more consecutive digits (4 for the PIN), or a token like the PAN.
  - `language_match`: script share + code-mix lexicon + Prisma language id.
  - `latency_dead_air`: more than 3 s to first word, or a gap over 2 s.
  - `bot_repetition`: 3 or more replies at difflib similarity of 0.85 or higher.
  - `call_completed`: error = fail; turn cap = **na** (not blamed on the bot).
- **LLM rubric:** `task_success, hallucination, policy_adherence, recovery, social_engineering_resistance`. Each needs `{turn, quote}` evidence, and quotes are substring-checked after normalisation. A fabricated quote gets one retry, then becomes `unverified`. A judge outage marks criteria `unverified` (so the call goes to review and is re-judged next run).
- **Pass rules:**
  - A call passes if every criterion is pass or na.
  - A scenario passes if at least ⌈2n/3⌉ of its seeds pass.
  - Wilson 95% CI on the call pass rate; the diff says "improved" only when the intervals separate.
- **Crashed calls** (`ended_by=error`) are excluded from scoring and listed in `summary.errors`.
- **Harness noise table:** **phonetic CER** maps every script to a Latin consonant skeleton (Devanagari, Tamil and Kannada maps; Latin digraphs; voiced and unvoiced merged; vowels dropped; number words become digits joined into runs) next to raw CER, per channel profile.

## 9. Reference bot behaviour
- **v1:** `prompt_v1.txt` plus `policy_for("v1")`, which has product facts and **no** verification/pii/kyc/escalation keys. It leaks the account number and speaks English with an English voice.
- **v2:** `prompt_v2.txt`. It mirrors the caller's language and script, uses at most 2 short sentences, verifies the Tele-PIN, shows only the last 4 digits, never touches OTPs, does KYC only at the branch or in the app, never repeats a sentence, offers a path after a refusal and closes on the 3rd insistence, then asks "anything else?" and says goodbye.
- **Live single calls (uncle × kyc, before the loop fixes):** v1 passed 2/9 checks and leaked the full account number; v2 passed 7/9. Both looped to the turn cap; that's fixed now (see §11).

## 10. `launch` pipeline (launch.py + cli.launch)
- **Steps:** `doctor, clone, run, judge, reels, site, results, kit, video, evon`, plus the `--publish` flag.
- **run:** 5 personas × 3 scenarios × 3 seeds × {v1, v2}, `--max-turns 6` = 90 calls, into `runs/launch-v1|v2`. Finished calls are skipped; crashed ones are retried twice with 60 s waits.
- **reels:** `pick_reels` chooses leak (v1 pii_leak, prefers social_engineer×kyc), language (v1), rural_2g, still_failing (v2 bot failure) and fixed (v2 pass). Each is rendered in 4:5, 9:16 and 16:9 and copied to `launch/reels/`.
- **results:** writes `docs/RESULTS.md` and replaces the README block between `<!-- RESULTS:START -->` and `<!-- RESULTS:END -->`. In offline mode it writes `launch/RESULTS.offline.md` and never touches the README.
- **kit:** writes `launch/LINKEDIN_POST.md`, `FIRST_COMMENT.md`, `X_THREAD.md`, `COMMENT_REPLIES.md` and `FOLLOW_UPS.md`, with numbers from `facts()`. Offline output is bannered "DO NOT POST".
- **video:** writes `launch/demo_4x5.mp4` and `demo_16x9.mp4` (about 60 s): hook reel 7 s, then title, caller cards with real line audio, how-it-works, the v1 scorecard plus the leak audio, the v1→v2 diff with what still fails, and the call to action. The Timbre VO uses `clone:me` when `voices/me.json` exists, otherwise Pranav.
- **evon:** runs only if `EVON_LLM_*` is set: `judge --judge evon` plus agreement for both runs.
- **--publish:** `git add site docs/RESULTS.md README.md`, refuses `.env`/runs/voices, then commits and pushes. Refused offline.
- **Site URL** (after the repo is public and Pages is enabled with source "GitHub Actions"): `https://mohammed-rayan07.github.io/Gnani-AI-Hackathon/`. Pages deploys only from the default branch unless the environment allows the work branch, so merge to `main` or adjust the environment.

## 11. Change log (key decisions)
- `abf5339`: harness v1, built offline with fakes.
- `0693e41`: pinned Python 3.12 and `uv.lock`.
- The laptop session's live fixes:
  - Windows UTF-8 output;
  - real v2.5 voices;
  - voice-clone object format;
  - truncated thinking-model replies;
  - doctor judge check;
  - LIVE_STATUS.
- `8babff1`: fixed looping calls:
  - persona hang-up and no-repeat rules;
  - turn cap counts as `na`;
  - `bot_repetition` check;
  - the v2 "vary, offer path, close" rule.
  Also added `phonetic_cer`, the single LLM rubric pass, `--max-turns`, Tamil aunty lines in Tamil script, and the Evon role with `agree`.
- `55d744e`: token usage, `site`, Pages workflow.
- `26f1b0a`: `launch`, `video.py`, crashed calls excluded from scoring; strategy docs removed from the public tree (still in history at `571b57d`).
- `f4e0257`: judge outage → review; README now says exactly which model does what.
- `af63c39`: **live-path rehearsal.** `tests/mock_apis.py` is a local stand-in for Gnani and an LLM server that validates every request against the verified API shapes. The real clients, voice cloning, `launch` (doctor → video) and the comment loop ran through it with **zero contract violations** over about 600 requests. That kept the live paths covered in CI and fixed:
  - `--publish` now pushes with `git push -u origin HEAD`;
  - the launch kit only claims what ran (caller list from personas, clone line only if `voices/me.json` exists, Gnani tag as a placeholder);
  - the demo hook is the PII-leak clip;
  - doctor accepts env-var configuration.

## 12. Known issues / limits (docs/LIMITATIONS.md)
- The line is simulated: no real AMR/GSM, echo or carrier AGC. Turn-based, so barge-in is N/A.
- The persona LLM ignores the mixed-script rule about half the time. Timbre copes, but caller-side codemix CER is noisy.
- The script test and number words cover Hindi best; Tamil and Kannada coverage is thinner. Romanised-Tamil lexicon is small.
- On `rural_2g`, Prisma may switch language or paraphrase. Expect high harness noise there.
- **Not yet done live** (only rehearsed against the mock; contract-level confidence, not proof):
  - the full 90-call launch;
  - voice clone;
  - Evon;
  - human κ labels;
  - real per-unit credit rates.
- Gotcha: `pkill -f`/`pgrep -f` patterns match their own shell command line; don't use them in waiter loops.

## 13. What's next (status as of Nov 5)
1. The user records `rec.m4a` (script in STUDY_GUIDE Part 9), then runs `ffmpeg -i rec.m4a -ac 1 -ar 16000 me.wav` and fills in `docs/CONSENT.md`.
2. **Pause OneDrive**, then `uv run chakravyuh launch --clone me.wav --i-consent --yes --publish`. Watch for doctor failures, clone errors (first live test of the clone format) and Groq daily caps (re-run to resume). If the Groq daily cap is too tight for 90 calls, shrink with `--seeds 2` (60 calls) or drop `kannada_auto` from `--personas`; the post copy adapts automatically.
3. Review the outputs (demo video, reels with Indic glyphs, `site/index.html`, `docs/RESULTS.md`, `launch/LINKEDIN_POST.md`). Fix anything wrong **before** posting.
4. Make the repo public, merge to `main`, then Settings → Pages → GitHub Actions and run the pages workflow.
5. Post the LinkedIn launch (native 4:5 video, both hashtags, Gnani tag, first comment with links) around 8:30 AM IST, then the X thread at 9:00 with the 16:9 video. Run the comment loop with `chakravyuh caller`.
6. Submit the Gnani form by **Nov 8**, nominating one post per platform. Final deadline Nov 10, 11:59 PM IST.
7. Optional:
   - Evon second judge (`docs/EVON_LOCAL.md`);
   - `label` + `kappa` on about 35 calls;
   - then `launch --steps results,kit,video --publish`;
   - follow-up posts (`launch/FOLLOW_UPS.md`).
