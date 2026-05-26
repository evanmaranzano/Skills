from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
ROOT = Path("F:/activitywatch-daily-log")
CONFIG_PATH = ROOT / "config" / "settings.json"
RAW_DIR = ROOT / "raw" / "activitywatch"
PROCESSED_DIR = ROOT / "processed"
REPORTS_DIR = ROOT / "reports"
PROMPTS_DIR = SKILL_ROOT / "prompts"


def ensure_dirs() -> None:
    for path in (RAW_DIR, PROCESSED_DIR, REPORTS_DIR, PROMPTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_day(day_text: str | None) -> date:
    if day_text:
        return datetime.strptime(day_text, "%Y-%m-%d").date()
    return datetime.now().date()


def day_bounds(target_day: date) -> tuple[str, str]:
    start_dt = datetime.combine(target_day, time.min)
    end_dt = start_dt + timedelta(days=1)
    return start_dt.isoformat(), end_dt.isoformat()
