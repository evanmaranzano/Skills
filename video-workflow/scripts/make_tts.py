#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TTS 生成（单人/双人通用）：读 beats.json → edge-tts 逐句合成 →
ffmpeg 按 beat 拼接（句间静音）→ 输出 24kHz mono wav + timing.json。

beats.json 结构（见 templates/beats.example.json）：
  [{"beat":1, "from":12, "dur":80, "rate":"+8%", "gap":0.18,
    "speaker_lines":[{"spk":"X","text":"..."}]}]

spk: "X"=晓晓(zh-CN-XiaoxiaoNeural) / "Y"=云希(zh-CN-YunxiNeural)。
单人模式：所有 speaker_lines 用同一个 spk，只传对应 --voice-* 即可。
from/dur 为 30fps 时间线帧；每段拼接后补齐/截断到 dur/30 秒窗口。

用法：
  python make_tts.py --beats beats.json --out clips/
  python make_tts.py --beats beats.json --out clips/ --voice-Y zh-CN-YunxiNeural   # 单人
  超窗（OVER）时：删该句字数或调大该 beat 的 rate（+18%~+20% 为可懂度上限），重跑。
"""
import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

try:
    import edge_tts
except ImportError:
    sys.exit("需要 edge-tts：pip install edge-tts")

VOICE_X = "zh-CN-XiaoxiaoNeural"
VOICE_Y = "zh-CN-YunxiNeural"


async def synth_one(text, voice, out, rate, retries=4):
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(str(out))
            if out.exists() and out.stat().st_size > 1000:
                return
        except Exception as e:
            print(f"  retry {attempt+1}: {e}", file=sys.stderr)
        await asyncio.sleep(1.5)
    raise RuntimeError(f"TTS failed: {text[:30]}")


def dur(p):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)],
        capture_output=True, text=True)
    return float(r.stdout.strip())


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--beats", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice-X", default=VOICE_X)
    ap.add_argument("--voice-Y", default=VOICE_Y)
    args = ap.parse_args()

    beats = json.loads(Path(args.beats).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    voices = {"X": args.voice_X, "Y": args.voice_Y}

    timing = []
    for b in beats:
        bid = b.get("beat", b.get("id", "?"))
        lines = b.get("speaker_lines") or [
            {"spk": b.get("speaker", "X"), "text": b["narration"]}
        ]
        rate = b.get("rate", "+10%")
        gap = b.get("gap", 0.18)
        win = b["dur"] / 30.0
        print(f"[beat {bid}] {len(lines)} lines, window {win:.2f}s")

        clip_paths = []
        line_timings = []
        cursor = 0.0
        for i, ln in enumerate(lines):
            spk = ln["spk"]
            text = ln["text"]
            mp3 = out / f"b{bid}_{i}_{spk}.mp3"
            await synth_one(text, voices[spk], mp3, rate)
            d = dur(mp3)
            line_timings.append({"spk": spk, "text": text, "dur": round(d, 3),
                                 "start": round(cursor, 3)})
            print(f"  {spk} {d:.2f}s  {text[:40]}")
            clip_paths.append(mp3)
            cursor += d
            if i < len(lines) - 1:
                cursor += gap

        total = cursor
        flag = "OK" if total <= win + 0.02 else f"OVER by {total-win:.2f}s"
        print(f"  -> total {total:.2f}s / window {win:.2f}s  {flag}")

        # ffmpeg concat with anullsrc gaps, pad/truncate to window
        inputs = []
        for idx, cp in enumerate(clip_paths):
            inputs += ["-i", str(cp)]
            if idx < len(clip_paths) - 1:
                inputs += ["-f", "lavfi", "-t", str(gap),
                           "-i", "anullsrc=r=24000:cl=mono"]
        n = len(clip_paths) + (len(clip_paths) - 1)
        concat = "".join(f"[{j}:a]" for j in range(n))
        fc = (f"{concat}concat=n={n}:v=0:a=1[a0];"
              f"[a0]aresample=24000,apad=whole_dur={win}[a]")
        wav_out = out / f"s{bid}.wav" if str(bid).isdigit() else out / f"b{bid}.wav"
        # normalize output name: use beat number if available
        wav_out = out / f"{b.get('wav', f's{bid}.wav')}"
        cmd = ["ffmpeg", "-y", "-v", "error"] + inputs + [
            "-filter_complex", fc, "-map", "[a]",
            "-ac", "1", "-ar", "24000", "-t", str(win), str(wav_out)]
        subprocess.run(cmd, check=True)
        print(f"  -> wav {wav_out.name} {dur(wav_out):.2f}s")

        timing.append({
            "beat": bid, "from": b["from"], "dur": b["dur"],
            "window_s": round(win, 3), "audio_s": round(total, 3),
            "wav": wav_out.name, "lines": line_timings,
        })

    (out / "timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTIMING_WRITTEN {out / 'timing.json'}")
    over = [t for t in timing if t["audio_s"] > t["window_s"] + 0.02]
    if over:
        print("⚠️ 以下段超窗口，请调大 rate 重跑：")
        for t in over:
            print(f"  beat {t['beat']}: {t['audio_s']:.2f}s > {t['window_s']:.2f}s")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
