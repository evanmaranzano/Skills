#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mixkit 免费商用 BGM 选曲 + 响度标定。

用法：
  python pick_bgm.py --list --tag ambient --min-sec 110        # 列出候选（按时长过滤）
  python pick_bgm.py --list --tag documentary --genre "Film Score"
  python pick_bgm.py --download <mp3_url> --out public/assets/audio/bgm/bgm-x.mp3

来源：Mixkit Stock Music Free License（免费商用、无需署名）。FreePD 已于 2026-09 关站。
下载后脚本输出 ffprobe 时长 + volumedetect 响度，并按「目标床 -30dB mean」给出
Remotion BGM_ENVELOPE 的铺底乘数与闪避值（闪避 = 铺底 × 0.4）。

依赖：scrapling（curl_cffi 指纹，mixkit 页面用普通 urllib 会被拦）；ffmpeg/ffprobe。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

TARGET_BED_DB = -30.0  # BGM 铺底目标响度（旁白峰值约 -10dB 时留足余量）
TAGS = ["ambient", "documentary", "inspiring", "corporate", "downtempo"]


def parse_dur(pt: str) -> int:
    m = re.match(r"PT(?:(\d+)M)?(\d+)S", pt or "")
    return int(m.group(1) or 0) * 60 + int(m.group(2)) if m else 0


def scrape(tag: str) -> dict[str, dict]:
    from scrapling.fetchers import Fetcher
    url = f"https://mixkit.co/free-stock-music/tag/{tag}/" if "-" not in tag else \
        f"https://mixkit.co/free-stock-music/discover/{tag}/"
    r = Fetcher.get(url, impersonate="chrome", timeout=30)
    out: dict[str, dict] = {}
    for m in re.finditer(r'\{"@id":"[^"]*","@type":"MusicRecording".*?\}(?=,\{"@id"|\])', r.html_content):
        try:
            d = json.loads(m.group(0))
        except Exception:
            continue
        if d.get("url", "").endswith(".mp3"):
            out[d["name"]] = {
                "dur": parse_dur(d.get("duration", "")),
                "genre": d.get("genre", ""),
                "artist": d.get("byArtist", ""),
                "url": d["url"],
            }
    return out


def cmd_list(args) -> int:
    seen: dict[str, dict] = {}
    for tag in [args.tag] if args.tag else TAGS:
        try:
            seen.update(scrape(tag))
        except Exception as e:
            print(f"[warn] {tag}: {e}", file=sys.stderr)
    rows = [(n, d) for n, d in seen.items() if d["dur"] >= args.min_sec
            and (not args.genre or d["genre"].lower() == args.genre.lower())]
    rows.sort(key=lambda kv: -kv[1]["dur"])
    print(f"{len(rows)} candidates >= {args.min_sec}s (Mixkit Free License, 免费商用免署名):")
    for n, d in rows:
        print(f"  {d['dur']//60}:{d['dur']%60:02d} [{d['genre']}] {n} — {d['artist']}")
        print(f"      {d['url']}")
    return 0


def cmd_download(args) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl", "-s", "-L", "-A", "Mozilla/5.0", "-o", str(out), args.download])
    if r.returncode != 0 or not out.exists() or out.stat().st_size < 100_000:
        sys.exit(f"下载失败：{args.url}")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
    vd = subprocess.run(["ffmpeg", "-v", "info", "-i", str(out), "-af", "volumedetect",
                         "-f", "null", "-"], capture_output=True, text=True).stderr
    mean = float(re.search(r"mean_volume: (-?[\d.]+) dB", vd).group(1))
    maxv = float(re.search(r"max_volume: (-?[\d.]+) dB", vd).group(1))
    mult = 10 ** ((TARGET_BED_DB - mean) / 20)
    duck = round(mult * 0.4, 3)
    print(f"saved: {out}  {dur:.1f}s  mean {mean:.1f} dB / max {maxv:.1f} dB")
    print(f"BGM_ENVELOPE 标定（目标床 {TARGET_BED_DB:.0f}dB）：")
    print(f"  铺底乘数 = {round(mult, 3)}   闪避值 = {duck}")
    print(f"  开头空窗检查：前 15s mean ", end="")
    vd15 = subprocess.run(["ffmpeg", "-v", "info", "-t", "15", "-i", str(out), "-af", "volumedetect",
                           "-f", "null", "-"], capture_output=True, text=True).stderr
    m15 = float(re.search(r"mean_volume: (-?[\d.]+) dB", vd15).group(1))
    print(f"{m15:.1f} dB" + ("  ⚠️ 开头偏弱，可给 Audio 加 startFrom 跳过弱起" if m15 < mean - 6 else "  OK"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--download", metavar="URL")
    ap.add_argument("--out", default="bgm.mp3")
    ap.add_argument("--tag", help="mixkit 分类/标签（ambient/documentary/...），--list 时可选")
    ap.add_argument("--genre", help="按 genre 精确过滤（如 'Film Score'）")
    ap.add_argument("--min-sec", type=int, default=110)
    args = ap.parse_args()
    if args.download:
        return cmd_download(args)
    return cmd_list(args)


if __name__ == "__main__":
    sys.exit(main())
