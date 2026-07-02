#!/usr/bin/env python3
"""Reporting utilities for kid-career-portrait-batch."""

import csv
import json
from datetime import datetime
from pathlib import Path


def write_manifest(records: list, output_dir: Path):
    """Write manifest.csv and manifest.json."""
    csv_path = output_dir / "manifest.csv"
    json_path = output_dir / "manifest.json"

    fieldnames = [
        "name",
        "gender",
        "career",
        "input_file",
        "output_file",
        "prompt",
        "status",
        "error",
        "created_at",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in fieldnames})

    json_records = []
    for r in records:
        json_records.append({k: r.get(k, "") for k in fieldnames})
    json_path.write_text(
        json.dumps(json_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_failed(records: list, output_dir: Path):
    """Write failed.json with all non-success records."""
    failed = [r for r in records if r.get("status") != "success"]
    (output_dir / "logs" / "failed.json").write_text(
        json.dumps(failed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_report(records: list, output_dir: Path, ppt_path: Path = None, lark_result_path: Path = None):
    """Write report.md summary."""
    total = len(records)
    success = sum(1 for r in records if r.get("status") == "success")
    skipped = sum(1 for r in records if r.get("status") == "skipped")
    failed = sum(1 for r in records if r.get("status") == "failed")

    lines = [
        "# Batch Career Portrait Report",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- Total: {total}",
        f"- Success: {success}",
        f"- Skipped (already existed): {skipped}",
        f"- Failed: {failed}",
        "",
    ]
    if ppt_path:
        lines.append(f"- PPTX: {ppt_path}")
    if lark_result_path:
        lines.append(f"- Lark publish result: {lark_result_path}")
    lines.extend([
        "",
        "| Name | Gender | Career | Status | Error |",
        "|---|---|---|---|---|",
    ])
    for r in records:
        name = r.get("name", "")
        gender = r.get("gender", "")
        career = r.get("career", "")
        status = r.get("status", "")
        error = r.get("error", "") or ""
        lines.append(f"| {name} | {gender} | {career} | {status} | {error} |")

    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
