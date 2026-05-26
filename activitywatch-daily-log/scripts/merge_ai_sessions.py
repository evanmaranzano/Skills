from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import PROCESSED_DIR, dump_json, ensure_dirs, load_json, parse_day


LOCAL_TZ = datetime.now().astimezone().tzinfo


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def overlaps_target_date(start_time: datetime, end_time: datetime, target_date: date) -> bool:
    from datetime import time as dt_time
    local_start = to_local(start_time)
    local_end = to_local(end_time)
    day_start = datetime.combine(target_date, dt_time.min, tzinfo=LOCAL_TZ)
    next_day = day_start + timedelta(days=1)
    return local_start < next_day and local_end >= day_start


def collect_claude_code(target_date: date, base_dir: str = "~/.claude/projects") -> list[dict]:
    """Collect Claude Code sessions for the target date."""
    sessions = []
    base_path = Path(os.path.expanduser(base_dir))
    if not base_path.exists():
        return sessions

    for project_dir in base_path.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = _parse_project_name(project_dir.name)
        for jsonl_file in project_dir.glob("*.jsonl"):
            if "subagent" in str(jsonl_file):
                continue
            session = _parse_claude_session(jsonl_file, project_name, target_date)
            if session:
                sessions.append(session)

    return sorted(sessions, key=lambda s: s["start_time"])


def _parse_project_name(dir_name: str) -> str:
    parts = dir_name.strip("-").split("-")
    skip_prefixes = {"Users", "jakevin", "code", "home"}
    meaningful = [p for p in parts if p not in skip_prefixes]
    return "-".join(meaningful[-2:]) if meaningful else dir_name


def _parse_claude_session(filepath: Path, project: str, target_date: date) -> dict | None:
    messages_count = 0
    timestamps = []
    first_prompt = ""
    context_lines = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = obj.get("type", "")
                ts = _extract_timestamp(obj)
                if ts:
                    timestamps.append(ts)

                if msg_type in ("human", "assistant"):
                    messages_count += 1
                    content = _extract_content(obj.get("message", {}))
                    if content:
                        role = "User" if msg_type == "human" else "AI"
                        context_lines.append(f"{role}: {content}")
                        if msg_type == "human" and not first_prompt:
                            first_prompt = content
                elif msg_type == "summary":
                    first_prompt = obj.get("summary", "") or first_prompt

    except (OSError, IOError):
        return None

    if not timestamps:
        return None

    start_time = to_local(min(timestamps))
    end_time = to_local(max(timestamps))

    if not overlaps_target_date(start_time, end_time, target_date):
        return None

    title = first_prompt[:150] if first_prompt else f"Claude Code session ({project})"
    full_context = "\n".join(context_lines)
    if len(full_context) > 5000:
        full_context = full_context[:5000] + "\n...[Truncated]"

    return {
        "id": filepath.stem,
        "source": "Claude Code",
        "project": project,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "title_or_prompt": title,
        "message_count": messages_count,
        "full_context": full_context,
    }


def collect_antigravity(target_date: date, brain_dir: str = "~/.gemini/antigravity/brain") -> list[dict]:
    """Collect Antigravity sessions for the target date."""
    sessions = []
    brain_path = Path(os.path.expanduser(brain_dir))
    if not brain_path.exists():
        return sessions

    for session_dir in brain_path.iterdir():
        if not session_dir.is_dir():
            continue
        session = _parse_antigravity_session(session_dir, target_date)
        if session:
            sessions.append(session)

    return sorted(sessions, key=lambda s: s["start_time"])


def _parse_antigravity_session(session_dir: Path, target_date: date) -> dict | None:
    timestamps = []
    title = ""
    context_lines = []

    # Try metadata files for timestamps
    for meta_file in session_dir.glob("*.metadata.json"):
        try:
            with open(meta_file, encoding="utf-8", errors="ignore") as f:
                meta = json.load(f)
            for ts_field in ("createdAt", "updatedAt", "lastModified"):
                ts_val = meta.get(ts_field)
                if ts_val:
                    ts = _parse_ts(ts_val)
                    if ts:
                        timestamps.append(ts)
            summary = meta.get("summary", "")
            if summary:
                title = summary[:150]
        except (json.JSONDecodeError, OSError):
            continue

    # Try markdown files for context
    for md_file in session_dir.glob("*.md"):
        if md_file.name.endswith(".metadata.json"):
            continue
        try:
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime, tz=timezone.utc)
            timestamps.append(mtime)
            content_text = md_file.read_text(encoding="utf-8")
            context_lines.append(f"Artifact Context [File: {md_file.name}]:")
            context_lines.append(content_text)
            if not title:
                for line in content_text.splitlines()[:5]:
                    line = line.strip()
                    if line.startswith("# "):
                        title = line[2:].strip()[:120]
                        break
        except OSError:
            continue

    if not timestamps:
        try:
            mtime = datetime.fromtimestamp(session_dir.stat().st_mtime, tz=timezone.utc)
            timestamps.append(mtime)
        except OSError:
            return None

    start_time = to_local(min(timestamps))
    end_time = to_local(max(timestamps))

    if not overlaps_target_date(start_time, end_time, target_date):
        return None

    full_context = "\n".join(context_lines)
    if len(full_context) > 5000:
        full_context = full_context[:5000] + "\n...[Truncated]"

    return {
        "id": session_dir.name,
        "source": "Antigravity",
        "project": "",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "title_or_prompt": title or f"Antigravity session",
        "message_count": len(list(session_dir.glob("*.md"))),
        "full_context": full_context,
    }


def _parse_ts(value) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (ValueError, OSError):
            pass
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def collect_codex(target_date: date, base_dir: str = "~/.codex/sessions") -> list[dict]:
    """Collect Codex sessions for the target date."""
    sessions = []
    base_path = Path(os.path.expanduser(base_dir))
    if not base_path.exists():
        return sessions

    for jsonl_file in base_path.glob("*.jsonl"):
        session = _parse_codex_session(jsonl_file, target_date)
        if session:
            sessions.append(session)

    return sorted(sessions, key=lambda s: s["start_time"])


def _parse_codex_session(filepath: Path, target_date: date) -> dict | None:
    messages_count = 0
    timestamps = []
    first_prompt = ""
    context_lines = []

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = obj.get("type", "")
                ts = _extract_timestamp(obj)
                if ts:
                    timestamps.append(ts)

                if msg_type in ("human", "assistant", "tool"):
                    messages_count += 1
                    content = _extract_content(obj.get("message", {}))
                    if content:
                        context_lines.append(f"{msg_type}: {content}")
                        if msg_type == "human" and not first_prompt:
                            first_prompt = content

    except (OSError, IOError):
        return None

    if not timestamps:
        return None

    start_time = to_local(min(timestamps))
    end_time = to_local(max(timestamps))

    if not overlaps_target_date(start_time, end_time, target_date):
        return None

    title = first_prompt[:150] if first_prompt else f"Codex session"
    full_context = "\n".join(context_lines)
    if len(full_context) > 5000:
        full_context = full_context[:5000] + "\n...[Truncated]"

    return {
        "id": filepath.stem,
        "source": "Codex",
        "project": "",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "title_or_prompt": title,
        "message_count": messages_count,
        "full_context": full_context,
    }


def _extract_timestamp(obj: dict) -> datetime | None:
    for field in ("timestamp", "cacheBreaker"):
        val = obj.get(field)
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                pass
    return None


def _extract_content(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return " ".join(texts).strip()
    return ""


def collect_gemini_cli(target_date: date, base_dir: str = "~/.gemini/history") -> list[dict]:
    """Collect Gemini CLI sessions for the target date."""
    sessions = []
    base_path = Path(os.path.expanduser(base_dir))
    if not base_path.exists():
        return sessions

    for session_dir in base_path.iterdir():
        if not session_dir.is_dir():
            continue
        session = _parse_gemini_session(session_dir, target_date)
        if session:
            sessions.append(session)

    return sorted(sessions, key=lambda s: s["start_time"])


def _parse_gemini_session(session_dir: Path, target_date: date) -> dict | None:
    # Try to read HISTORY.md or similar files
    history_files = list(session_dir.glob("HISTORY.md")) + list(session_dir.glob("*.md"))
    if not history_files:
        return None

    timestamps = []
    title = ""
    context_lines = []

    for hist_file in history_files[:1]:  # Only first history file
        try:
            content = hist_file.read_text(encoding="utf-8")
            timestamps.append(datetime.fromtimestamp(hist_file.stat().st_mtime, tz=timezone.utc))
            context_lines.append(content[:3000])
            for line in content.splitlines()[:3]:
                line = line.strip()
                if line.startswith("# "):
                    title = line[2:].strip()[:120]
                    break
        except OSError:
            continue

    if not timestamps:
        return None

    start_time = to_local(min(timestamps))
    end_time = to_local(max(timestamps))

    if not overlaps_target_date(start_time, end_time, target_date):
        return None

    return {
        "id": session_dir.name,
        "source": "Gemini CLI",
        "project": "",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "title_or_prompt": title or f"Gemini CLI session",
        "message_count": 0,
        "full_context": "\n".join(context_lines)[:5000],
    }


def merge_ai_sessions(into_summary: dict, ai_sessions: list[dict]) -> dict:
    """Merge AI tool sessions into the summary data."""
    if "ai_sessions" not in into_summary:
        into_summary["ai_sessions"] = []

    # Get existing AI sessions to avoid duplicates
    existing_ids = {s["id"] for s in into_summary["ai_sessions"]}
    for session in ai_sessions:
        if session["id"] not in existing_ids:
            into_summary["ai_sessions"].append(session)

    # Sort by start_time
    into_summary["ai_sessions"].sort(key=lambda s: s["start_time"])

    return into_summary


def process_day(day_text: str | None) -> int:
    ensure_dirs()
    target_day = parse_day(day_text)
    summary_path = PROCESSED_DIR / f"{target_day.isoformat()}.summary.json"
    if not summary_path.exists():
        print(f"找不到聚合数据文件：{summary_path}", file=sys.stderr)
        return 1

    summary = load_json(summary_path)

    # Collect AI tool sessions
    all_sessions = []
    all_sessions.extend(collect_claude_code(target_day))
    all_sessions.extend(collect_antigravity(target_day))
    all_sessions.extend(collect_codex(target_day))
    all_sessions.extend(collect_gemini_cli(target_day))

    print(f"收集到 {len(all_sessions)} 个 AI 会话")

    # Merge into summary
    merged = merge_ai_sessions(summary, all_sessions)
    dump_json(summary_path, merged)

    print(f"已合并 AI 会话数据到：{summary_path}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="day_text", help="日期，格式 YYYY-MM-DD")
    args = parser.parse_args()
    raise SystemExit(process_day(args.day_text))
