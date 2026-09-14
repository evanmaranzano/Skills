#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义音效 Spotting：beats.json(+timing.json) → sfx-cues.yaml + 可粘贴的 SFX 时间线数组。

方法论：references/creator-methodology.md §5（吸收自 Justin-Video-Factory / knowledge-video-sfx）
- 音效是第三信息通道：一声 = 一次可解释的状态迁移（定位/因果/确认/风险/收束），不为每个动画制造存在感
- 身份声：同一事件全片固定同一素材；conclusion.slam 全片 ≤3 处
- 相邻 cue ≥ --min-gap 秒（不可分的单一事件合成一声，不叠两声）
- 密度档位（复查线不是配额）：sparse 2.0–3.5 / balanced 3.5–5.0 / dense 4.5–6.0 条/分钟

事件→语音锚点（确定性规则，产出后人工复查 sfx-cues.yaml 再挂渲染）：
  开篇定调/终场收束 → conclusion.slam；风险词 → risk.flag；确认/建议词 → check.confirm；
  因果词 → flow.connect；vector 镜头入场 → card.enter；画面族切换 → scene.transition

用法：
  python make_sfx.py --beats beats.json --timing clips/timing.json --copy-to public/assets/audio/sfx
  # 输出 <out>（默认 sfx-cues.yaml），并把 const SFX = [...] 片段打到 stdout（粘贴进 index.tsx）

依赖：pyyaml；素材目录默认 = 本 skill assets/sfx/（Mixkit Free License，免费商用免署名）。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
PROFILE = {"sparse": (2.0, 3.5), "balanced": (3.5, 5.0), "dense": (4.5, 6.0)}
GAIN = {"conclusion.slam": 0.30, "risk.flag": 0.22, "check.confirm": 0.18, "card.lock": 0.16,
        "flow.connect": 0.15, "card.enter": 0.13, "scene.transition": 0.13}
PRIO = {"conclusion.slam": 3.0, "risk.flag": 2.5, "check.confirm": 2.0, "flow.connect": 1.5,
        "scene.transition": 1.2, "card.enter": 1.0}
FUNC = {"conclusion.slam": "emphasis", "risk.flag": "caution", "check.confirm": "resolution",
        "card.lock": "commitment", "flow.connect": "causality", "card.enter": "orientation",
        "scene.transition": "transition"}

RISK_W = ["不是", "误区", "错误", "危害", "坏处", "风险", "警告", "小心", "陷阱", "骗",
          "警惕", "过量", "超标", "伤", "更糟", "恶化", "反弹", "白吃", "白喝", "白花钱"]
CONFIRM_W = ["建议", "应该", "记住", "正确", "方法", "三步", "通过", "达标", "做到", "换成",
             "选择", "第一步", "第二步", "第三步", "就够了", "就够了", "攻略", "诀窍", "口诀"]
CONNECT_W = ["因为", "导致", "所以", "因此", "意味着", "就会", "变成", "会让", "让它", "等于",
             "相当于", "背后", "原理", "机制", "为什么"]


def family(vt: str) -> str:
    return "h3" if (vt or "").startswith("h3") else "vector"


def load_catalog(path: Path) -> dict:
    cat = yaml.safe_load(path.read_text(encoding="utf-8"))
    ev_assets: dict[str, list] = {}
    for ev, assets in (cat.get("events") or {}).items():
        for a in assets or []:
            a["_dir"] = path.parent
            ev_assets.setdefault(ev, []).append(a)
    return ev_assets


def candidate_cues(beats: list, timing: dict | None, fps: int) -> list:
    cues: list = []
    n = len(beats)

    def abs_start(b):
        return b["from"] / fps

    for i, b in enumerate(beats):
        bid = b.get("beat", i + 1)
        bt0 = abs_start(b)
        lines = (timing or {}).get(bid) or []
        vt = b.get("visual_type", "")
        # 开篇定调 / 终场收束
        if i == 0 or i == n - 1:
            cues.append({"beat": bid, "t": round(bt0 + 0.10, 3), "event": "conclusion.slam",
                         "why": "开篇定调" if i == 0 else "终场收束",
                         "anchor": (b.get("narration") or "")[:24]})
        # 画面族切换 → 转场声（低频使用）
        if i > 0 and family(beats[i - 1].get("visual_type", "")) != family(vt):
            cues.append({"beat": bid, "t": round(bt0, 3), "event": "scene.transition",
                         "why": "画面族切换", "anchor": (b.get("narration") or "")[:24]})
        # vector 镜头入场
        if family(vt) == "vector":
            cues.append({"beat": bid, "t": round(bt0 + 0.15, 3), "event": "card.enter",
                         "why": "vector 镜头对象入场", "anchor": (b.get("narration") or "")[:24]})
        # 逐句关键词扫描（risk > confirm > connect，每句最多一声）
        for ln in lines:
            text = ln.get("text", "")
            t = bt0 + float(ln.get("start", 0.0)) + 0.05
            ev = None
            if any(w in text for w in RISK_W):
                ev = "risk.flag"
            elif any(w in text for w in CONFIRM_W):
                ev = "check.confirm"
            elif any(w in text for w in CONNECT_W):
                ev = "flow.connect"
            if ev:
                cues.append({"beat": bid, "t": round(t, 3), "event": ev,
                             "why": "口播锚点句", "anchor": text[:24]})
    return cues


def merge(cues: list, min_gap: float, slam_cap: int) -> tuple[list, list]:
    """按优先级贪婪保留（priority 降序、时间升序），强制相邻间隔与 slam 上限。"""
    kept, dropped = [], []
    slam_n = 0
    for c in sorted(cues, key=lambda c: (-PRIO[c["event"]], c["t"])):
        if c["event"] == "conclusion.slam":
            if slam_n >= slam_cap:
                dropped.append((c, "slam 超上限")); continue
            slam_n += 1
        if any(abs(c["t"] - k["t"]) < min_gap for k in kept):
            dropped.append((c, f"与已保留 cue 间隔 < {min_gap}s")); continue
        kept.append(c)
    kept.sort(key=lambda c: c["t"])
    return kept, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beats", required=True)
    ap.add_argument("--timing", default=None, help="clips/timing.json（缺省时按 beat 起点锚定）")
    ap.add_argument("--out", default="sfx-cues.yaml")
    ap.add_argument("--catalog", default=str(SKILL_DIR / "assets" / "sfx" / "sfx-catalog.yaml"))
    ap.add_argument("--profile", default="balanced", choices=list(PROFILE))
    ap.add_argument("--min-gap", type=float, default=3.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--copy-to", default=None, help="把选用素材复制到该目录（事件名命名）")
    args = ap.parse_args()

    beats = json.loads(Path(args.beats).read_text(encoding="utf-8"))
    timing: dict = {}
    if args.timing:
        for t in json.loads(Path(args.timing).read_text(encoding="utf-8")):
            timing[t["beat"]] = t.get("lines", [])
    ev_assets = load_catalog(Path(args.catalog))
    missing = [e for e in PRIO if e not in ev_assets]
    if missing:
        sys.exit(f"catalog 缺事件素材: {missing}")

    cues = candidate_cues(beats, timing, args.fps)
    kept, dropped = merge(cues, args.min_gap, slam_cap=3)

    dur_s = max(b["from"] + b["dur"] for b in beats) / args.fps
    lo, hi = PROFILE[args.profile]
    # 超密度：只从 supporting 级裁剪；primary（slam/risk）是骨架，保留到底并告警
    while len(kept) / dur_s * 60 > hi:
        supporting = [c for c in kept if PRIO[c["event"]] < 2.5]
        if not supporting:
            print(f"⚠️ 密度 {len(kept)/dur_s*60:.1f}/min 超区间但剩余全为 primary，停止裁剪", file=sys.stderr)
            break
        lowest = min(supporting, key=lambda c: PRIO[c["event"]])
        kept.remove(lowest)
        dropped.append((lowest, "超出密度区间裁剪"))

    # 事件→素材（身份声：每事件固定 primary 素材）
    for c in kept:
        a = ev_assets[c["event"]][0]
        c["asset"] = a
        c["gain"] = GAIN[c["event"]]

    # 写 sfx-cues.yaml
    doc = {
        "schema_version": 1,
        "project": {"id": Path(args.beats).parent.name, "catalog": args.catalog,
                    "sources": {"narration": args.beats, "timing": args.timing},
                    "timing_authority": "final_audio_or_srt" if args.timing else "script_anchors"},
        "density_plan": {"profile": args.profile, "duration_s": round(dur_s, 2),
                         "target_cues_per_min": [lo, hi],
                         "planned_cue_count": len(kept),
                         "planned_cues_per_min": round(len(kept) / dur_s * 60, 2)},
        "cues": [{
            "id": f"sfx-{i+1:03d}", "scene_id": f"beat-{c['beat']}",
            "event": c["event"], "function": FUNC[c["event"]],
            "priority": "primary" if PRIO[c["event"]] >= 2.5 else "supporting",
            "visual_anchor": {"action": c["why"], "trigger": "impact"},
            "narration_anchor": {"text": c["anchor"]},
            "timing": {"at_s": c["t"], "offset_ms": 0},
            "selected": {"asset_id": c["asset"]["asset_id"], "file": f"{c['event'].replace('.', '-')}.mp3",
                         "gain": c["gain"]},
            "status": "needs_audition", "rationale": c["why"],
        } for i, c in enumerate(kept)],
        "omitted": [{"beat": c["beat"], "event": c["event"], "t": c["t"], "reason": r}
                    for c, r in dropped],
    }
    Path(args.out).write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    if args.copy_to:
        dst = Path(args.copy_to)
        dst.mkdir(parents=True, exist_ok=True)
        for c in {c["event"]: c for c in kept}.values():
            shutil.copyfile(Path(c["asset"]["_dir"]) / c["asset"]["file"],
                            dst / f"{c['event'].replace('.', '-')}.mp3")

    # 报告 + 可粘贴时间线
    print(f"SFX_CUES {args.out}  {len(kept)} cues / {dur_s:.0f}s = {len(kept)/dur_s*60:.1f}/min "
          f"(target {lo}-{hi})")
    for c in kept:
        print(f"  {c['t']:7.2f}s  beat{c['beat']:<3} {c['event']:<18} gain {c['gain']}  {c['anchor']}")
    if dropped:
        print(f"  静音决定 {len(dropped)} 条（见 {args.out} omitted 段）")
    print("\n// ↓ 粘贴进 index.tsx（替换 const SFX = []）")
    print("const SFX: { from: number; dur: number; src: string; vol: number; note?: string }[] = [")
    for c in kept:
        fr = round(c["t"] * args.fps)
        dfr = max(1, round(c["asset"]["duration_ms"] / 1000 * args.fps) + 2)
        print(f"  {{ from: {fr}, dur: {dfr}, src: 'assets/audio/sfx/"
              f"{c['event'].replace('.', '-')}.mp3', vol: {c['gain']}, note: '{c['event']}' }},")
    print("];")
    return 0


if __name__ == "__main__":
    sys.exit(main())
