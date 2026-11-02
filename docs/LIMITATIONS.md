# What CHAKRAVYUH can't do (yet)

- **The phone line is simulated.** It covers band-pass, 8 kHz, μ-law or low-bitrate opus, Gilbert-Elliott burst loss and clipping. It does **not** cover real AMR/GSM codec artefacts, echo, carrier AGC or jitter-buffer time-warping. The next validation step is real calls through a telephony provider.
- **Turn-based, not full duplex.** The harness uses Prisma REST so that runs are parallel, cached and replayable. Barge-in and interruption handling are therefore reported as N/A. A streaming mode is future work.
- **No word timestamps from Prisma.** Latency and dead air come from a VAD run on the bot's own audio, plus adapter timings.
- **Language match is approximate.** It combines script share, a small code-mix lexicon and Prisma's language id. Romanised Tamil and Kannada coverage is thin.
- **The LLM judge is not ground truth.** Deterministic checks gate first, quotes are machine-verified, and agreement with hand labels (Cohen's κ) is published per run.
- **Spoken-number normalisation covers English, Hindi, Tamil and Kannada digit words.** Other languages are caught only when Prisma writes digits.
- **Comment-loop languages are limited** to the 10 that Prisma and Timbre support. Others are mapped to the nearest supported language, and the reply says so.
- **Offline mode** (`CHAKRAVYUH_OFFLINE=1`) only proves the plumbing works. Its numbers are meaningless and every page is stamped to say so.
