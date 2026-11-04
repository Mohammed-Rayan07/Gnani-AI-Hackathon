"""Crash reels: a short captioned clip of one call, built for the feed.

Audio is the real phone-line audio (8 kHz, noisy) so viewers hear what the bot
heard. Captions are burned in with libass (it shapes Devanagari/Tamil/Kannada
correctly when the font has the script; on Windows "Nirmala UI" covers them).
Every reel carries a "SYNTHETIC CALLER" watermark.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import audio
from .models import CallRecord

SIZES = {"4:5": (1080, 1350), "9:16": (1080, 1920), "16:9": (1920, 1080)}
FONT = os.environ.get("CHAKRAVYUH_REEL_FONT", "Nirmala UI")
OUT_SR = 16000
CRIT_SHORT = {"pii_leak": "PII LEAK", "language_match": "LANGUAGE MISMATCH", "latency_dead_air": "DEAD AIR",
              "call_completed": "CALL CRASHED", "bot_repetition": "STUCK IN A LOOP", "task_success": "TASK FAILED", "hallucination": "HALLUCINATION",
              "policy_adherence": "POLICY BREACH", "recovery": "NO RECOVERY",
              "social_engineering_resistance": "SOCIAL-ENGINEERED"}


def _ts(t: float) -> str:
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def _verdict(run_dir: Path, call_id: str) -> dict | None:
    p = run_dir / "verdicts.json"
    if not p.exists():
        return None
    return next((v for v in json.loads(p.read_text(encoding="utf-8")) if v["call_id"] == call_id), None)


def _focus_turns(call: CallRecord, verdict: dict | None) -> list[int]:
    ev = []
    if verdict and not verdict["passed"]:
        for c in verdict["criteria"]:
            if c["status"] == "fail":
                ev += [e["turn"] for e in c.get("evidence", []) if isinstance(e.get("turn"), int)]
    key = min(ev) if ev else 1
    return [i for i in (key - 1, key) if i >= 1] or [1]


def render_reel(run_dir: Path, call_id: str, *, max_seconds: float = 15.0, aspect: str = "4:5", out: Path | None = None) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
    run_dir = Path(run_dir)
    cdir = run_dir / "calls" / call_id
    call = CallRecord.model_validate_json((cdir / "call.json").read_text(encoding="utf-8"))
    verdict = _verdict(run_dir, call_id)
    W, H = SIZES[aspect]
    turns = {t.index: t for t in call.turns}

    pieces, events, t = [], [], 0.0
    gap = audio.silence(0.25, OUT_SR)
    for i in _focus_turns(call, verdict):
        tr = turns.get(i)
        if tr is None:
            continue
        for who, key, text in (("CALLER", "caller_line", tr.caller_text), ("BOT", "bot_line", tr.bot_text_true or tr.bot_text_heard)):
            if key not in tr.audio:
                continue
            x, sr = audio.read_wav(cdir / tr.audio[key])
            x = audio.resample(x, sr, OUT_SR)
            x = x / (np.max(np.abs(x)) + 1e-9) * 0.9          # caller and bot at similar loudness
            if t + len(x) / OUT_SR > max_seconds - 2.0:
                x = x[: max(0, int((max_seconds - 2.0 - t) * OUT_SR))]
            if not len(x):
                break
            pieces += [x, gap]
            events.append((t, t + len(x) / OUT_SR, who, text))
            t += len(x) / OUT_SR + 0.25
    if not pieces:
        raise RuntimeError(f"No audio found for {call_id}")
    stamp_at = t
    pieces.append(audio.silence(2.0, OUT_SR))
    total = t + 2.0
    track = np.concatenate(pieces)

    if verdict is None:
        stamp, colour = "NOT JUDGED", "&H00FFFFFF"
    elif verdict["passed"]:
        stamp, colour = "PASS", "&H00409A2E"
    else:
        names = [CRIT_SHORT.get(c["name"], c["name"].upper()) for c in verdict["criteria"] if c["status"] == "fail"]
        stamp, colour = "FAIL\\N" + ("\\N".join(names[:2]) or "REVIEW"), "&H002B35C2"

    fs = int(W * 0.042)
    ass = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Head,{FONT},{int(fs * 1.1)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,8,60,60,{int(H * 0.06)},1",
        f"Style: Mark,{FONT},{int(fs * 0.6)},&H80FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,2,0,1,0,0,8,60,60,{int(H * 0.06 + fs * 1.6)},1",
        f"Style: Caller,{FONT},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,0,0,3,14,0,2,70,70,{int(H * 0.18)},1",
        f"Style: Bot,{FONT},{fs},&H0000E5FF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,0,0,3,14,0,2,70,70,{int(H * 0.18)},1",
        f"Style: Stamp,{FONT},{int(fs * 1.35)},&H00FFFFFF,&H00FFFFFF,{colour},{colour},1,0,0,0,100,100,2,0,3,22,0,5,90,90,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{_ts(0)},{_ts(total)},Head,,0,0,0,,{_ass_escape(call.persona_id.replace('_', ' ').title())} → {_ass_escape(call.bot_label)}",
        f"Dialogue: 0,{_ts(0)},{_ts(total)},Mark,,0,0,0,,SYNTHETIC CALLER · {call.channel} line · CHAKRAVYUH",
    ]
    for a, b, who, text in events:
        ass.append(f"Dialogue: 0,{_ts(a)},{_ts(b + 0.2)},{'Caller' if who == 'CALLER' else 'Bot'},,0,0,0,,{who}: {_ass_escape(text)}")
    ass.append(f"Dialogue: 1,{_ts(stamp_at)},{_ts(total)},Stamp,,0,0,0,,{stamp}")   # names are fixed labels; \\N = line break

    out = Path(out) if out else run_dir / "reels" / f"{call_id}_{aspect.replace(':', 'x')}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        audio.write_wav(Path(d) / "a.wav", track, OUT_SR)
        (Path(d) / "c.ass").write_text("\n".join(ass), encoding="utf-8")
        wave_h = int(H * 0.22)
        fc = (f"[1:a]showwaves=s={W - 160}x{wave_h}:mode=cline:rate=30:colors=0x7C5CFF|0x7C5CFF[w];"
              f"[0:v][w]overlay=(W-w)/2:(H-h)/2-{int(H * 0.05)}[v1];[v1]subtitles=c.ass[v]")
        cmd = ["ffmpeg", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", f"color=c=0x111014:s={W}x{H}:r=30:d={total:.2f}",
               "-i", "a.wav", "-filter_complex", fc, "-map", "[v]", "-map", "1:a",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "21",
               "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest", "-movflags", "+faststart", str(out.resolve())]
        subprocess.run(cmd, check=True, cwd=d)
    return out
