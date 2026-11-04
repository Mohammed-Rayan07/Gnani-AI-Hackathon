# Runbook

Run every command from the repo root with `uv run chakravyuh ...`. You can also activate `.venv` first and drop the `uv run`.

## Once
| Step | Command | Done when |
|---|---|---|
| Install | `uv venv` then `uv pip install -e ".[dev]"` then `uv run pytest -q` | the tests pass |
| Configure | copy `.env.example` to `.env`, fill in the keys | – |
| Verify | `chakravyuh doctor` | every check shows OK |
| Calibrate cost | `chakravyuh smoke`, then read the app.gnani.ai usage page and set `RATE_*` in `.env` | rates set |
| Clone your voice | `ffmpeg -i rec.m4a -ac 1 -ar 16000 me.wav` then `chakravyuh clone-voice me.wav --name me --i-consent` | `voices/me.json` exists |

## One call (sanity check, a few rupees)
```
chakravyuh run --bot inprocess:v1 --personas uncle_traffic --scenarios kyc_otp_pressure --seeds 1 --yes
chakravyuh judge runs/<run>
chakravyuh report runs/<run>          # open runs/<run>/scorecard.html
```

## Full regression (about ₹300–450 of credits, check the estimate it prints)
```
chakravyuh run --bot inprocess:v1 --yes --tag launch
chakravyuh run --bot inprocess:v2 --yes --tag launch
chakravyuh judge runs/<v1>  ;  chakravyuh judge runs/<v2>
chakravyuh report runs/<v1> ;  chakravyuh report runs/<v2>
chakravyuh diff runs/<v1> runs/<v2>
chakravyuh label runs/<v1> --limit 35 ; chakravyuh kappa runs/<v1>
```

## Content
```
chakravyuh reel runs/<run> <call_id> --aspect 4:5     # LinkedIn
chakravyuh reel runs/<run> <call_id> --aspect 9:16    # X / shorts
chakravyuh caller "<comment text>"                      # comment loop; prints a ready-made reply
chakravyuh budget                                       # credits spent so far
```

## When something breaks
- Run `chakravyuh doctor` first. Every failing check prints a fix.
- An HTTP 400/422 from Gnani means a field name differs from what the docs led us to expect. Paste the full error.
- HTTP 429 means you hit a free-tier limit. The client waits it out; keep `CONCURRENCY=2`.
