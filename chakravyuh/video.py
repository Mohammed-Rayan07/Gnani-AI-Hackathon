"""The 60-second demo video, assembled automatically from the judged runs.

Storyboard (docs: plan section 8): hook clip -> "N calls, not one caller real" -> caller cards with
their real line audio -> how it works -> v1 scorecard + the leak audio -> v1 -> v2 + what still fails
-> call to action. Every number on screen comes from facts() (the judged runs). The voice-over is
Timbre: your cloned voice when voices/me.json exists, a stock voice otherwise. Offline builds carry a
"NOT REAL RESULTS" banner for their whole length.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio, models
from .reel import FONT, _ass_escape, _ts

SR = 16000
SIZES = {"4:5": (1080, 1350), "16:9": (1920, 1080), "9:16": (1080, 1920)}


@dataclass
class Segment:
    name: str
    min_s: float
    lines: list[tuple[str, str]]                 # (style, text) shown for the whole segment
    vo: str = ""
    clip: np.ndarray | None = None               # extra audio under/after the VO
    clip_at: float = 0.0
    stagger: bool = False                        # reveal lines one after another
    audio: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))


def _extract_audio(mp4: Path, seconds: float) -> np.ndarray:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "a.wav"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp4), "-t", f"{seconds:.2f}", "-ac", "1",
                        "-ar", str(SR), str(out)], check=True)
        x, _ = audio.read_wav(out)
    return x


def _snippet(run_dir: Path, call_id: str, key: str, seconds: float) -> np.ndarray | None:
    cdir = run_dir / "calls" / call_id
    p = cdir / "call.json"
    if not p.exists():
        return None
    call = json.loads(p.read_text(encoding="utf-8"))
    for t in call["turns"]:
        if key in t.get("audio", {}):
            x, sr = audio.read_wav(cdir / t["audio"][key])
            x = audio.resample(x, sr, SR)[: int(seconds * SR)]
            return x / (np.max(np.abs(x)) + 1e-9) * 0.8
    return None


def _evidence_bot_audio(run_dir: Path, call_id: str, criterion: str, seconds: float) -> np.ndarray | None:
    vs = json.loads((run_dir / "verdicts.json").read_text(encoding="utf-8"))
    v = next((x for x in vs if x["call_id"] == call_id), None)
    turn = None
    if v:
        for c in v["criteria"]:
            if c["name"] == criterion and c.get("evidence"):
                turn = c["evidence"][0].get("turn")
    cdir = run_dir / "calls" / call_id
    call = json.loads((cdir / "call.json").read_text(encoding="utf-8"))
    for t in call["turns"]:
        if (turn is None or t["index"] == turn) and "bot_line" in t.get("audio", {}):
            x, sr = audio.read_wav(cdir / t["audio"]["bot_line"])
            x = audio.resample(x, sr, SR)[: int(seconds * SR)]
            return x / (np.max(np.abs(x)) + 1e-9) * 0.8
    return None


async def _vo(tts, text: str, voice: str) -> np.ndarray:
    if not text:
        return np.zeros(0, dtype=np.float32)
    x, sr = await tts.synthesize(text, voice=voice, language="en-IN")
    x = audio.resample(x, sr, SR)
    return x / (np.max(np.abs(x)) + 1e-9) * 0.9


async def build_demo(f: dict, picks: dict, reels: dict, tts, voices_dir: Path, out_dir: Path, v1_dir: Path,
                     aspects=("4:5", "16:9"), repo_url: str = "", log=print) -> list[Path]:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
    cloned = (voices_dir / "me.json").exists()
    vo_voice = "clone:me" if cloned else os.environ.get("DEMO_VO_VOICE", "Pranav")
    if getattr(tts, "label", None) and "offline" in str(tts.label("x")):
        vo_voice = vo_voice.replace("clone:", "")
    n, cells = f["calls_total"], f["cells_total"]
    P = models.personas()

    hook_key = "language" if "language" in reels else ("leak" if "leak" in reels else None)
    segs: list[Segment] = []
    # 2. title
    segs.append(Segment("title", 3.2, [("Big", f"{n} phone calls to a voice bot."), ("Sub", "Not one caller was real.")],
                        vo=f"I made {n} phone calls to a voice bot. Not one caller was real."))
    # 3. callers with their real line audio
    callers = []
    for pid in f["personas"]:
        p = P.get(pid)
        if not p:
            continue
        hits = sorted((v1_dir / "calls").glob(f"{pid}__*"))
        clip = _snippet(v1_dir, hits[0].name, "caller_line", 1.8) if hits else None
        callers.append((p, clip))
    for p, clip in callers:
        segs.append(Segment(f"caller-{p.id}", 2.0, [("Card", p.name), ("Small", f"{p.summary} · {p.channel.replace('_', ' ')} line")],
                            clip=clip, clip_at=0.1))
    # 4. how it works
    judge = f["judge_model"] or "An LLM"
    if judge.startswith("deterministic"):
        judge = "Rule-based checks"
    how_vo = ("None of these callers are real. The uncle is me, cloned with Gnani's Timbre." if cloned else
              "None of these callers are real. Gnani's Timbre voices them, and Prisma listens.")
    segs.append(Segment("how", 8.0, [("Head", "How it works"),
                                     ("Line", "1. Timbre voices the caller" + (" (the uncle is my cloned voice)" if cloned else "")),
                                     ("Line", "2. A phone-line simulator adds 8 kHz, noise, packet loss"),
                                     ("Line", "3. The bot answers"),
                                     ("Line", "4. Prisma hears it through the same bad line"),
                                     ("Line", f"5. {judge} judges, quoting the exact words")], vo=how_vo, stagger=True))
    # 5. scorecard + the leak audio
    leak = picks.get("leak")
    leak_clip = _evidence_bot_audio(leak[0], leak[1], "pii_leak", 4.5) if leak else None
    segs.append(Segment("scorecard", 9.0, [("Head", "First-draft bot (v1)"),
                                           ("Big", f"{f['v1_cells']}/{cells} scenarios passed"),
                                           ("Sub", f"{f['v1_leaks']} calls read out a fake account number")],
                        vo="Every failure comes with the audio, so you can hear exactly what broke.",
                        clip=leak_clip, clip_at=None))
    # 6. diff
    still = f["top_still_human"]
    segs.append(Segment("diff", 8.0, [("Head", "Hardened bot (v2)"),
                                      ("Big", f"v1 {f['v1_cells']}/{cells}  →  v2 {f['v2_cells']}/{cells}"),
                                      ("Sub", f"Still failing: {still}" if still else "Nothing failed. Time for harder callers.")],
                        vo=(f"Version two fixes most of it. It still {still}." if still else "Version two passes this matrix.")))
    # 7. end card
    segs.append(Segment("end", 5.5, [("Big", "Describe a caller in the comments."), ("Sub", "I'll make them call the bot."),
                                     ("Small", "All callers synthetic · Gnani Prisma · Timbre · Evon" + (f" · {repo_url}" if repo_url else ""))],
                        vo="Describe a caller in the comments, and I'll make them call the bot."))

    # audio per segment
    for sg in segs:
        vo = await _vo(tts, sg.vo, vo_voice)
        parts = [vo]
        total = max(sg.min_s, len(vo) / SR + 0.5)
        if sg.clip is not None and len(sg.clip):
            at = (len(vo) / SR + 0.3) if sg.clip_at is None else sg.clip_at
            total = max(total, at + len(sg.clip) / SR + 0.4)
        track = np.zeros(int(total * SR), dtype=np.float32)
        track[: len(vo)] += vo
        if sg.clip is not None and len(sg.clip):
            a = int(at * SR)
            seg = sg.clip[: len(track) - a]
            track[a:a + len(seg)] += seg * (0.55 if sg.clip_at is not None and len(vo) else 1.0)
        sg.audio = track

    hook_s = 0.0
    hook_audio = np.zeros(0, dtype=np.float32)
    outputs = []
    for aspect in aspects:
        W, H = SIZES[aspect]
        hook_mp4 = reels.get(hook_key, {}).get(aspect) or reels.get(hook_key, {}).get("4:5") if hook_key else None
        if hook_mp4 and Path(hook_mp4).exists():
            hook_s = 7.0
            hook_audio = _extract_audio(Path(hook_mp4), hook_s)
            hook_audio = np.pad(hook_audio, (0, max(0, int(hook_s * SR) - len(hook_audio))))
        track = np.concatenate([hook_audio] + [sg.audio for sg in segs])
        track = np.clip(track, -1, 1)
        total = len(track) / SR

        fs = int(W * 0.05)
        styles = {
            "Big": (int(fs * 1.25), "&H00FFFFFF", 1, 5, 0), "Sub": (int(fs * 0.85), "&H00FFC3C9", 0, 5, int(H * 0.09)),
            "Head": (int(fs * 0.7), "&H00FF96A9", 1, 8, int(H * 0.12)), "Card": (int(fs * 1.1), "&H00FFFFFF", 1, 5, 0),
            "Small": (int(fs * 0.55), "&H00B0B0B0", 0, 2, int(H * 0.08)), "Line": (int(fs * 0.62), "&H00FFFFFF", 0, 7, 0),
            "Banner": (int(fs * 0.55), "&H0000C8FF", 1, 8, 20),
        }
        ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "", "[V4+ Styles]",
               "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"]
        for name, (size, col, bold, align, mv) in styles.items():
            ass.append(f"Style: {name},{FONT},{size},{col},&H00FFFFFF,&H00000000,&H00000000,{-1 if bold else 0},0,0,0,100,100,0,0,1,0,0,{align},{int(W * 0.07)},{int(W * 0.07)},{mv},1")
        ass += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
        t = hook_s
        for sg in segs:
            d = len(sg.audio) / SR
            y0 = int(H * 0.30)
            for k, (style, text) in enumerate(sg.lines):
                start = t + (0.6 + k * 0.9 if sg.stagger and style == "Line" else 0.0)
                if style == "Line":
                    tag = f"{{\\an7\\pos({int(W * 0.08)},{y0 + k * int(fs * 1.25)})}}"
                elif style == "Sub" and sg.name.startswith("caller"):
                    tag = f"{{\\an5\\pos({W // 2},{int(H * 0.58)})}}"
                elif style == "Big" and any(st == "Sub" for st, _ in sg.lines):
                    tag = f"{{\\an5\\pos({W // 2},{int(H * 0.44)})}}"
                elif style == "Sub":
                    tag = f"{{\\an5\\pos({W // 2},{int(H * 0.56)})}}"
                else:
                    tag = ""
                ass.append(f"Dialogue: 0,{_ts(start)},{_ts(t + d)},{style},,0,0,0,,{tag}{_ass_escape(text)}")
            t += d
        if f["offline"]:
            ass.append(f"Dialogue: 2,{_ts(0)},{_ts(total)},Banner,,0,0,0,,OFFLINE DRY RUN · NOT REAL RESULTS")
        else:
            ass.append(f"Dialogue: 2,{_ts(hook_s)},{_ts(total)},Banner,,0,0,0,,SYNTHETIC CALLERS · CHAKRAVYUH")

        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"demo_{aspect.replace(':', 'x')}.mp4"
        with tempfile.TemporaryDirectory() as d:
            audio.write_wav(Path(d) / "a.wav", track, SR)
            (Path(d) / "d.ass").write_text("\n".join(ass), encoding="utf-8")
            wh = int(H * 0.12)
            inputs = ["-f", "lavfi", "-i", f"color=c=0x111014:s={W}x{H}:r=30:d={total:.2f}"]
            fc = []
            base = "[0:v]"
            idx_audio = 1
            if hook_s:
                inputs += ["-i", str(Path(hook_mp4).resolve())]
                fc.append(f"[1:v]trim=0:{hook_s},setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=decrease,"
                          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x111014[hook]")
                fc.append(f"{base}[hook]overlay=0:0:eof_action=pass[b]")
                base = "[b]"
                idx_audio = 2
            inputs += ["-i", "a.wav"]
            fc.append(f"[{idx_audio}:a]showwaves=s={W - 160}x{wh}:mode=cline:rate=30:colors=0x7C5CFF[w]")
            fc.append(f"{base}[w]overlay=(W-w)/2:H-h-{int(H * 0.16)}:enable='gte(t,{hook_s})'[c]")
            fc.append("[c]subtitles=d.ass[v]")
            cmd = ["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(fc),
                   "-map", "[v]", "-map", f"{idx_audio}:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                   "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest", "-movflags", "+faststart",
                   str(out.resolve())]
            subprocess.run(cmd, check=True, cwd=d)
        log(f"    demo video {aspect}: {out} ({total:.0f}s)")
        outputs.append(out)
    return outputs
