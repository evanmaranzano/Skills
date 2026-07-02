#!/usr/bin/env python3
"""Filename parsing utilities for kid-career-portrait-batch."""

from pathlib import Path


GENDER_ALIASES = {
    "男": "男",
    "男孩": "男",
    "男生": "男",
    "boy": "男",
    "male": "男",
    "m": "男",
    "女": "女",
    "女孩": "女",
    "女生": "女",
    "girl": "女",
    "female": "女",
    "f": "女",
}


def normalize_gender(value: str) -> str:
    """Return normalized gender text or empty string when not provided."""
    if not value:
        return ""
    return GENDER_ALIASES.get(value.strip().lower(), GENDER_ALIASES.get(value.strip(), ""))


def parse_filename(stem: str, separators: list) -> tuple:
    """Return (name, career) or (None, None) if unparseable.

    Backward-compatible wrapper for older callers. Gender, if present, is ignored.
    """
    parsed = parse_filename_details(stem, separators)
    if not parsed:
        return None, None
    return parsed["name"], parsed["career"]


def parse_filename_details(stem: str, separators: list) -> dict | None:
    """Parse image filename metadata.

    Supported forms:
    - 姓名 职业.jpg
    - 姓名 性别 职业.jpg
    - Same rules for configured separators, e.g. 姓名_女_医生.jpg
    """
    for sep in separators:
        if sep not in stem:
            continue
        parts = [p.strip() for p in stem.split(sep) if p.strip()]
        if len(parts) < 2:
            continue
        name = parts[0]
        gender = ""
        career_parts = parts[1:]
        if len(parts) >= 3:
            maybe_gender = normalize_gender(parts[1])
            if maybe_gender:
                gender = maybe_gender
                career_parts = parts[2:]
        career = sep.join(career_parts).strip()
        if name and career:
            return {"name": name, "gender": gender, "career": career}
    return None


def scan_images(input_dir: Path, recursive: bool, allowed_ext: list) -> list:
    """Scan input directory for image files with allowed extensions."""
    results = []
    glob_fn = input_dir.rglob if recursive else input_dir.glob
    for f in sorted(glob_fn("*")):
        if f.is_file() and f.suffix.lower() in allowed_ext:
            results.append(f)
    return results
