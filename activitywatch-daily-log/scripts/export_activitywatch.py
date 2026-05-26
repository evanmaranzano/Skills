from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from common import RAW_DIR, day_bounds, dump_json, ensure_dirs, load_json, load_settings, parse_day


SAMPLE_PATH = RAW_DIR.parent.parent / "sample_data" / "activitywatch_sample.json"


def fetch_json(url: str, timeout_seconds: float = 15) -> Any:
    with urlopen(url, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"ActivityWatch API 返回了非 JSON 响应：{raw[:200]}")


def get_buckets(base_url: str, timeout_seconds: float) -> dict:
    return fetch_json(f"{base_url}/buckets", timeout_seconds)


def get_events(
    base_url: str, bucket_id: str, start: str, end: str, timeout_seconds: float
) -> list[dict]:
    query = urlencode({"start": start, "end": end})
    return fetch_json(f"{base_url}/buckets/{bucket_id}/events?{query}", timeout_seconds)


def export_day(day_text: str | None, use_sample: bool = False) -> int:
    ensure_dirs()
    target_day = parse_day(day_text)
    output_path = RAW_DIR / f"{target_day.isoformat()}.json"

    if use_sample:
        sample_payload = load_json(SAMPLE_PATH)
        sample_payload["date"] = target_day.isoformat()
        dump_json(output_path, sample_payload)
        print(f"已写入示例 ActivityWatch 数据: {output_path}")
        return 0

    settings = load_settings()
    activitywatch_settings = settings["activitywatch"]
    base_url = activitywatch_settings["base_url"].rstrip("/")
    timeout_seconds = float(activitywatch_settings.get("request_timeout_seconds", 15))
    preferred_keywords = tuple(
        keyword.lower() for keyword in activitywatch_settings["preferred_bucket_keywords"]
    )
    start, end = day_bounds(target_day)

    try:
        buckets = get_buckets(base_url, timeout_seconds)
    except (HTTPError, URLError, TimeoutError, ConnectionError) as exc:
        print(
            f"导出失败：无法连接 ActivityWatch API `{base_url}`。请确认 ActivityWatch 已启动。原始错误：{exc}",
            file=sys.stderr,
        )
        return 1

    payload = {
        "date": target_day.isoformat(),
        "start": start,
        "end": end,
        "selected_bucket_ids": [],
        "bucket_errors": {},
        "buckets": {},
    }

    for bucket_id, meta in buckets.items():
        bucket_key = f"{bucket_id} {json.dumps(meta, ensure_ascii=False)}".lower()
        if preferred_keywords and not any(keyword in bucket_key for keyword in preferred_keywords):
            continue
        try:
            events = get_events(base_url, bucket_id, start, end, timeout_seconds)
        except (HTTPError, URLError, TimeoutError, ConnectionError, ValueError) as exc:
            payload["bucket_errors"][bucket_id] = str(exc)
            print(f"跳过 bucket `{bucket_id}`：读取事件失败：{exc}", file=sys.stderr)
            continue
        payload["selected_bucket_ids"].append(bucket_id)
        payload["buckets"][bucket_id] = {
            "meta": meta,
            "events": events,
        }

    dump_json(output_path, payload)
    print(f"已导出 ActivityWatch 数据: {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="day_text", help="日期，格式 YYYY-MM-DD")
    parser.add_argument("--use-sample", action="store_true", help="使用本地示例数据，不连接 ActivityWatch")
    args = parser.parse_args()
    return export_day(args.day_text, use_sample=args.use_sample)


if __name__ == "__main__":
    raise SystemExit(main())
