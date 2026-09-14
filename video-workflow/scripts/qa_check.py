#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片自动验收：ffprobe 规格 + H3 屏占比 + 按帧表抽全场景帧 + H3 底缘条带 + 响度窗口。

用法（在项目目录下）：
  python <skill>/scripts/qa_check.py --video ./final_<proj>.mp4 --beats beats.json --public ./public

自动检查（PASS/FAIL 打到 stdout，规格/时长/占比 FAIL 时 exit 1）：
  1. 规格：时长=总帧数/fps（±0.5s）、1920x1080、h264+aac
  2. H3 屏占比：sum(H3 beat dur)/sum(全部 dur)（红线默认 >= 1/3，--min-h3 可改）
  3. 抽帧：每个 beat 场景中点（避开首尾 15% 转场淡）→ qa_frames/B<N>_*.png，供人工目检
  4. H3 底缘条带：public/assets/video/h3_*.mp4 各抽一张底部条带 → qa_frames/strip_h3_*.png
     （查模型烙印文字；有字的片段在 index.tsx 里给该 H3Clip 加 zoomFrom>=1.2）
  5. 响度：第一个 beat 的旁白窗 / 纯 BGM 窗（旁白结束后到 beat 尾）/ 结尾淡出窗
  6. SFX（--sfx-cues 时）：密度区间、conclusion.slam ≤3、相邻 cue ≥3s、素材文件在 public 下
人工目检 qa_frames/ 后才算验收通过。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FPS = 30


def ffprobe(path: Path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
                        "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(r.stdout)


def vol_window(video: Path, ss: float, t: float) -> tuple[float, float] | None:
    r = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(ss), "-t", str(t), "-i", str(video),
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    mean = maxv = None
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            m = re.search(r"(-?[\d.]+) dB", line)
            mean = float(m.group(1)) if m else None
        if "max_volume" in line:
            m = re.search(r"(-?[\d.]+) dB", line)
            maxv = float(m.group(1)) if m else None
    return (mean, maxv) if mean is not None else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--beats", required=True)
    ap.add_argument("--public", default="./public", help="项目 public 目录（H3 素材在 assets/video/）")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--min-h3", type=float, default=1 / 3, help="H3 屏占红线（默认 1/3）")
    ap.add_argument("--sfx-cues", default=None, help="sfx-cues.yaml（提供则做音效层校验）")
    ap.add_argument("--out", default="qa_frames", help="抽帧输出目录")
    args = ap.parse_args()

    video = Path(args.video)
    beats = json.loads(Path(args.beats).read_text(encoding="utf-8"))
    outdir = Path(args.out)
    outdir.mkdir(exist_ok=True)
    fails = []

    # 1. 规格
    info = ffprobe(video)
    fmt, streams = info["format"], {s["codec_type"]: s for s in info["streams"]}
    dur = float(fmt["duration"])
    total_frames = sum(b["dur"] for b in beats)
    v, a = streams.get("video", {}), streams.get("audio", {})
    print(f"[spec] duration {dur:.2f}s (帧表 {total_frames/FPS:.2f}s) | "
          f"{v.get('codec_name')} {v.get('width')}x{v.get('height')} @{v.get('r_frame_rate')} | {a.get('codec_name')}")
    if abs(dur - total_frames / FPS) > 0.5:
        fails.append(f"时长偏差 >0.5s：{dur:.2f} vs {total_frames/FPS:.2f}")
    if v.get("width") != 1920 or v.get("height") != 1080:
        fails.append(f"分辨率非 1080p：{v.get('width')}x{v.get('height')}")
    if v.get("codec_name") != "h264" or a.get("codec_name") != "aac":
        fails.append("编码非 h264+aac")

    # 2. H3 屏占比
    h3_frames = sum(b["dur"] for b in beats if str(b.get("visual_type", "")).startswith("h3"))
    ratio = h3_frames / total_frames
    flag = "PASS" if ratio >= args.min_h3 else "FAIL"
    print(f"[h3] 屏占 {h3_frames}/{total_frames} 帧 = {ratio*100:.1f}%（红线 {args.min_h3*100:.1f}%）{flag}")
    if ratio < args.min_h3:
        fails.append(f"H3 屏占 {ratio*100:.1f}% < {args.min_h3*100:.1f}%")

    # 3. 场景中点抽帧（避开首尾 15% 转场）
    n_ok = 0
    for b in beats:
        mid_s = (b["from"] + b["dur"] / 2) / FPS
        lead = (b["from"] + b["dur"] * 0.15) / FPS
        tail = (b["from"] + b["dur"] * 0.85) / FPS
        ts = min(max(mid_s, lead), tail)  # 中点若落在转场带内则取带内最靠中位置
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ts:.2f}", "-i", str(video),
                            "-frames:v", "1", str(outdir / f"B{b['beat']:02d}.png")])
        n_ok += r.returncode == 0
    print(f"[frames] {n_ok}/{len(beats)} 场景中点帧 → {outdir}/B*.png（人工目检：黑屏/豆腐块/重叠/溢出）")

    # 4. H3 底缘条带（烙印文字检查）
    vids = sorted(Path(args.public, "assets/video").glob("h3_*.mp4"))
    for vp in vids:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2", "-i", str(vp), "-frames:v", "1",
                        "-vf", "crop=1344:140:0:628,scale=1344:140",
                        str(outdir / f"strip_{vp.stem}.png")], check=False)
    if vids:
        print(f"[strips] {len(vids)} 张 H3 底缘条带 → {outdir}/strip_*.png（有烙印文字的片段加 zoomFrom>=1.2）")

    # 5. 响度窗口（第一拍旁白 / 第一个 ≥0.9s 纯BGM 空隙 / 结尾淡出）
    b1 = beats[0]
    w = vol_window(video, b1["from"] / FPS + 0.2, 2.0)
    if w:
        print(f"[audio] 旁白窗 beat1: mean {w[0]:.1f} dB / max {w[1]:.1f} dB"
              + ("  ⚠️ 旁白偏弱（峰值宜 >= -10dB）" if w[1] < -12 else ""))
    for prev, nxt in zip(beats, beats[1:]):
        gap0 = (prev["from"] + prev["dur"]) / FPS
        gap1 = nxt["from"] / FPS
        if gap1 - gap0 >= 0.9:  # 至少 0.9s 空隙才是纯床
            w = vol_window(video, gap0 + 0.05, min(1.5, gap1 - gap0 - 0.1))
            if w:
                print(f"[audio] 纯BGM床 @{gap0:.1f}s: mean {w[0]:.1f} dB / max {w[1]:.1f} dB"
                      + ("  ⚠️ 床偏响（宜 <= -28dB mean）" if w[0] > -26 else ""))
            break
    w = vol_window(video, dur - 2.0, 2.0)
    if w:
        print(f"[audio] 结尾淡出: mean {w[0]:.1f} dB / max {w[1]:.1f} dB")

    # 6. SFX 层校验（提供 --sfx-cues 时）
    if args.sfx_cues:
        try:
            import yaml
            doc = yaml.safe_load(Path(args.sfx_cues).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[sfx] 跳过（读不了 {args.sfx_cues}: {e}）")
            doc = None
        if doc:
            cues = doc.get("cues") or []
            plan = doc.get("density_plan") or {}
            per_min = plan.get("planned_cues_per_min", 0.0)
            lo, hi = (plan.get("target_cues_per_min") or [3.5, 5.0])
            slam = sum(1 for c in cues if c.get("event") == "conclusion.slam")
            gaps_bad = sum(1 for x, y in zip(cues, cues[1:])
                           if y.get("timing", {}).get("at_s", 0) - x.get("timing", {}).get("at_s", 0) < 3.0)
            miss = [c["selected"]["file"] for c in cues
                    if not Path(args.public, "assets/audio/sfx", c["selected"]["file"]).exists()]
            ok = lo <= per_min <= hi and slam <= 3 and gaps_bad == 0 and not miss
            print(f"[sfx] {len(cues)} cues = {per_min}/min（{lo}-{hi}）| slam {slam}/3 | "
                  f"间隔<3s: {gaps_bad} | 缺素材: {len(miss)} {'PASS' if ok else 'FAIL'}")
            if not ok:
                if not (lo <= per_min <= hi):
                    fails.append(f"SFX 密度 {per_min}/min 超出 {lo}-{hi}")
                if slam > 3:
                    fails.append(f"conclusion.slam {slam} > 3")
                if gaps_bad:
                    fails.append(f"SFX 相邻间隔 <3s 的对数 {gaps_bad}")
                if miss:
                    fails.append(f"SFX 素材缺文件: {miss}")

    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("\nPASS（自动项全过；抽帧/条带仍需人工目检）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
