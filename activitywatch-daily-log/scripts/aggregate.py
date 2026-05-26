from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import PROCESSED_DIR, RAW_DIR, dump_json, ensure_dirs, load_json, parse_day


def parse_started(event: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))


def event_end_timestamp(event: dict[str, Any]) -> float:
    start_dt = parse_started(event)
    duration = float(event.get("duration", 0))
    return start_dt.timestamp() + duration


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """合并重叠的时间区间。"""
    if not intervals:
        return []
    sorted_ivs = sorted(intervals)
    merged = [sorted_ivs[0]]
    for start, end in sorted_ivs[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _invert_intervals(
    intervals: list[tuple[float, float], ...],
    bounds: tuple[float, float],
) -> list[tuple[float, float]]:
    """反转区间：返回 bounds 内不在 intervals 中的部分。"""
    if not intervals:
        return [bounds]
    result = []
    cursor = bounds[0]
    for start, end in sorted(intervals):
        if start > cursor:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < bounds[1]:
        result.append((cursor, bounds[1]))
    return result


def _clip_to_intervals(
    event_start: float,
    event_end: float,
    allowed: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """将事件时间范围裁剪到 allowed 区间列表内，返回重叠部分。"""
    result = []
    for a_start, a_end in allowed:
        overlap_start = max(event_start, a_start)
        overlap_end = min(event_end, a_end)
        if overlap_start < overlap_end:
            result.append((overlap_start, overlap_end))
    return result


def aggregate_day(day_text: str | None) -> int:
    ensure_dirs()
    target_day = parse_day(day_text)
    raw_path = RAW_DIR / f"{target_day.isoformat()}.json"
    if not raw_path.exists():
        print(f"找不到原始数据文件：{raw_path}", file=sys.stderr)
        return 1

    raw_payload = load_json(raw_path)

    # 按 app+domain 聚合
    agg_data: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "duration": 0.0,
        "event_count": 0,
        "apps": set(),
        "domains": set(),
        "titles": set(),
        "categories": set(),
        "sample_titles": [],
    })

    afk_seconds = 0.0
    has_afk_bucket = False
    non_afk_windows: list[tuple[float, float]] = []
    afk_intervals: list[tuple[float, float]] = []
    activity_windows: list[tuple[float, float]] = []
    timeline_entries: list[dict[str, Any]] = []

    # Pass 1: 收集 AFK 区间
    for bucket_id, bucket_payload in raw_payload["buckets"].items():
        meta = bucket_payload["meta"]
        bucket_text = f"{bucket_id} {meta}".lower()

        if "aw-watcher-afk" in bucket_text:
            has_afk_bucket = True
            for event in bucket_payload["events"]:
                data = event.get("data", {})
                duration = float(event.get("duration", 0))
                status = str(data.get("status", "")).lower()
                if status == "afk":
                    afk_seconds += duration
                    start_dt = parse_started(event)
                    start_ts = start_dt.timestamp()
                    end_ts = event_end_timestamp(event)
                    afk_intervals.append((start_ts, end_ts))
                else:
                    start_dt = parse_started(event)
                    start_ts = start_dt.timestamp()
                    end_ts = event_end_timestamp(event)
                    non_afk_windows.append((start_ts, end_ts))
            break

    merged_afk = _merge_intervals(afk_intervals) if afk_intervals else []

    # 计算活跃时间窗口（AFK 反转）
    if has_afk_bucket and non_afk_windows:
        # 用 AFK watcher 的非 AFK 窗口
        active_seconds_source = "afk"
        active_bounds = _merge_intervals(non_afk_windows)
    elif has_afk_bucket:
        # 有 AFK bucket 但无非 AFK 窗口，用 AFK 反转
        active_seconds_source = "activity_fallback"
        day_start = target_day.timestamp()
        day_end = day_start + 86400
        active_bounds = _invert_intervals(merged_afk, (day_start, day_end))
    else:
        active_seconds_source = "activity"
        active_bounds = []

    active_seconds = round(sum(end - start for start, end in active_bounds), 2)

    # Pass 2: 聚合窗口事件（裁剪掉 AFK 时段）
    for bucket_id, bucket_payload in raw_payload["buckets"].items():
        meta = bucket_payload["meta"]
        bucket_text = f"{bucket_id} {meta}".lower()

        if "aw-watcher-afk" in bucket_text:
            continue

        for event in bucket_payload["events"]:
            duration = float(event.get("duration", 0))
            data = event.get("data", {})
            start_dt = parse_started(event)
            start_ts = start_dt.timestamp()
            end_ts = event_end_timestamp(event)
            activity_windows.append((start_ts, end_ts))

            app = str(data.get("app", "")) or str(data.get("app_name", "")) or "unknown"
            title = str(data.get("title", ""))
            domain = ""
            url = str(data.get("url", ""))
            from urllib.parse import urlparse
            if "://" in url:
                parsed = urlparse(url)
                domain = parsed.netloc

            # 过滤空值
            app = app.strip() or "unknown"
            title = title.strip() if title else ""
            domain = domain.strip() if domain else ""

            key = f"{app}|{domain}"

            # 裁剪到非 AFK 时段
            if merged_afk:
                clipped = _clip_to_intervals(start_ts, end_ts, active_bounds)
                clipped_duration = sum(e - s for s, e in clipped)
            else:
                clipped_duration = duration
                clipped = [(start_ts, end_ts)]

            is_during_afk = clipped_duration < 0.5 and duration > 10

            agg_data[key]["duration"] += clipped_duration
            agg_data[key]["event_count"] += 1
            agg_data[key]["apps"].add(app)
            if domain:
                agg_data[key]["domains"].add(domain)
            if title:
                agg_data[key]["titles"].add(title)
                if len(agg_data[key]["sample_titles"]) < 3:
                    agg_data[key]["sample_titles"].append(title)

            timeline_entries.append({
                "key": key,
                "start": start_dt.isoformat(),
                "end": (start_dt + timedelta(seconds=duration)).isoformat(),
                "duration_seconds": round(clipped_duration, 2),
                "raw_duration_seconds": round(duration, 2),
                "app": app,
                "domain": domain,
                "title": title,
                "summary_hint": title or app or domain or "unknown",
                "category": "未分类",
                "confidence": None,
                "during_afk": is_during_afk,
            })

    # 构建聚合结果
    aggregated = []
    for key, data in agg_data.items():
        agg_entry = {
            "key": key,
            "duration_seconds": round(data["duration"], 2),
            "event_count": data["event_count"],
            "apps": sorted(data["apps"]),
            "domains": sorted(data["domains"]),
            "sample_titles": data["sample_titles"],
        }
        aggregated.append(agg_entry)

    # 按时长排序
    aggregated.sort(key=lambda x: x["duration_seconds"], reverse=True)
    timeline_entries.sort(key=lambda x: x["start"])

    summary = {
        "date": target_day.isoformat(),
        "active_seconds": active_seconds,
        "active_seconds_source": active_seconds_source,
        "afk_seconds": round(afk_seconds, 2),
        "aggregated": aggregated,
        "aggregated_count": len(aggregated),
        "timeline_block_count": sum(data["event_count"] for data in agg_data.values()),
    }

    dump_json(PROCESSED_DIR / f"{target_day.isoformat()}.summary.json", summary)
    dump_json(PROCESSED_DIR / f"{target_day.isoformat()}.timeline.json", timeline_entries)
    print(f"已生成聚合结果：{target_day.isoformat()} ({len(aggregated)} 个组合)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="day_text", help="日期，格式 YYYY-MM-DD")
    args = parser.parse_args()
    return aggregate_day(args.day_text)


if __name__ == "__main__":
    raise SystemExit(main())
