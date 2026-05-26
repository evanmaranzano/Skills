from __future__ import annotations

import argparse
import json

from common import PROCESSED_DIR, PROMPTS_DIR, ensure_dirs, load_json, parse_day


def build_html_prompt(day_text: str | None) -> int:
    """Build prompt for LLM HTML generation with original data + classification results."""
    ensure_dirs()
    target_day = parse_day(day_text)
    base_prompt = (PROMPTS_DIR / "html_gen_prompt.md").read_text(encoding="utf-8")
    summary_path = PROCESSED_DIR / f"{target_day.isoformat()}.summary.json"
    timeline_path = PROCESSED_DIR / f"{target_day.isoformat()}.timeline.json"

    summary_payload = load_json(summary_path)
    timeline_payload = []
    if timeline_path.exists():
        try:
            loaded_timeline = load_json(timeline_path)
            if isinstance(loaded_timeline, list):
                timeline_payload = loaded_timeline
        except Exception:
            timeline_payload = []

    # Build pseudo-timeline from aggregated items when real timeline is absent
    if timeline_payload:
        timeline_payload = _apply_summary_classification(timeline_payload, summary_payload)
        timeline_payload = _merge_timeline_blocks(timeline_payload)
        trimmed_timeline = _sample_timeline(timeline_payload, limit=30)
        timeline_source_count = len(timeline_payload)
    else:
        aggregated = summary_payload.get("aggregated", [])
        pseudo_timeline = []
        for item in aggregated:
            entry = {
                "key": item.get("key", ""),
                "duration_seconds": item.get("duration_seconds", 0),
                "event_count": item.get("event_count", 0),
                "apps": item.get("apps", []),
                "domains": item.get("domains", []),
                "sample_titles": item.get("sample_titles", []),
                "category": item.get("category", ""),
                "confidence": item.get("confidence", None),
            }
            pseudo_timeline.append(entry)
        trimmed_timeline = _sample_timeline(pseudo_timeline, limit=30)
        timeline_source_count = len(pseudo_timeline)
    truncation_note = ""
    if timeline_source_count > 30:
        truncation_note = f"\n注意：时间线共 {timeline_source_count} 条，以下抽样展示开头、中段和末尾共 {len(trimmed_timeline)} 条。"

    # Get AI sessions if available
    ai_sessions = summary_payload.get("ai_sessions", [])
    ai_sessions_payload = ""
    if ai_sessions:
        ai_sessions_payload = json.dumps(ai_sessions, ensure_ascii=False, indent=2)

    parts = [
        base_prompt,
        f"\n日期：{target_day.isoformat()}",
        "你只需要直接返回 HTML 字符串，不要申请权限，不要描述将要写文件，也不要解释。",
        "原始数据 (summary JSON):",
        json.dumps(summary_payload, ensure_ascii=False, indent=2),
        "\n时间线 (timeline JSON):",
        json.dumps(trimmed_timeline, ensure_ascii=False, indent=2),
    ]
    if ai_sessions_payload:
        parts.append("\nAI 工具会话数据 (AI Sessions):")
        parts.append(ai_sessions_payload)
    if truncation_note:
        parts.append(truncation_note)
    full_prompt = "\n\n".join(parts)

    output_path = PROMPTS_DIR / f"{target_day.isoformat()}.prompt.txt"
    output_path.write_text(full_prompt, encoding="utf-8")
    print(f"已生成 prompt：{output_path}")
    return 0


def _apply_summary_classification(timeline: list[dict], summary_payload: dict) -> list[dict]:
    """Fill timeline category/confidence from aggregated summary by key."""
    by_key = {
        item.get("key", ""): item
        for item in summary_payload.get("aggregated", [])
        if isinstance(item, dict) and item.get("key")
    }
    enriched = []
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        source = by_key.get(str(item.get("key", "")))
        if source:
            if not item.get("category") or item.get("category") == "未分类":
                item["category"] = source.get("category", item.get("category", "未分类"))
            if item.get("confidence") is None:
                item["confidence"] = source.get("confidence")
            if source.get("classify_reason") and not item.get("classify_reason"):
                item["classify_reason"] = source.get("classify_reason")
        enriched.append(item)
    return enriched


def _merge_timeline_blocks(timeline: list[dict]) -> list[dict]:
    """Merge adjacent entries with the same key/category to reduce event noise."""
    blocks: list[dict] = []
    for entry in timeline:
        key = entry.get("key", "")
        category = entry.get("category", "")
        if blocks and blocks[-1].get("key") == key and blocks[-1].get("category", "") == category:
            block = blocks[-1]
            block["end"] = entry.get("end", block.get("end", ""))
            block["duration_seconds"] = round(
                float(block.get("duration_seconds", 0)) + float(entry.get("duration_seconds", 0)),
                2,
            )
            block["event_count"] = int(block.get("event_count", 1)) + 1
            if entry.get("summary_hint") and entry.get("summary_hint") not in str(block.get("summary_hint", "")):
                block["summary_hint"] = f"{block.get('summary_hint', '')} | {entry.get('summary_hint', '')}"
            # AFK 标记：仅当合并后所有条目都在 AFK 期间时才保留
            if entry.get("during_afk") and block.get("during_afk"):
                block["during_afk"] = True
            else:
                block["during_afk"] = False
            continue
        item = dict(entry)
        item.setdefault("event_count", 1)
        blocks.append(item)
    return blocks


def _sample_timeline(timeline: list[dict], limit: int = 30) -> list[dict]:
    """Sample timeline to show beginning, middle, and end."""
    if len(timeline) <= limit:
        return timeline

    group_size = limit // 3
    middle_start = max(group_size, len(timeline) // 2 - group_size // 2)
    tail_start = max(middle_start + group_size, len(timeline) - group_size)
    indices = [
        *range(0, group_size),
        *range(middle_start, middle_start + group_size),
        *range(tail_start, len(timeline)),
    ]
    seen: set[int] = set()
    sampled: list[dict] = []
    for index in indices:
        if 0 <= index < len(timeline) and index not in seen:
            sampled.append(timeline[index])
            seen.add(index)
    return sampled[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="day_text", help="日期，格式 YYYY-MM-DD")
    args = parser.parse_args()
    return build_html_prompt(args.day_text)


if __name__ == "__main__":
    raise SystemExit(main())
