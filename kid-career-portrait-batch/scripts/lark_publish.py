#!/usr/bin/env python3
"""Publish generated PPTX and Base records to Lark/Feishu via lark-cli."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


TABLE_NAME = "儿童未来职业照"
BASE_FIELDS = [
    {"type": "text", "name": "真名"},
    {"type": "text", "name": "期望职业"},
    {"type": "text", "name": "prompt"},
    {"type": "text", "name": "生成状态"},
]


def _lark_cli() -> str:
    found = shutil.which("lark-cli") or shutil.which("lark-cli.cmd")
    if found:
        return found
    npm_shim = Path(os.environ.get("APPDATA", "")) / "npm" / "lark-cli.cmd"
    if npm_shim.exists():
        return str(npm_shim)
    return "lark-cli"


def _run(cmd: list[str], cwd: Path | None = None) -> dict[str, Any]:
    if cmd and cmd[0] == "lark-cli":
        cmd = [_lark_cli(), *cmd[1:]]
    proc = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8", cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{proc.stderr or proc.stdout}")
    text = proc.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def _find_key(obj: Any, keys: set[str]) -> Any:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and v:
                return v
        for v in obj.values():
            found = _find_key(v, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_key(item, keys)
            if found:
                return found
    return None


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def _relative_for_lark(path: Path, cwd: Path, bucket: str) -> str:
    path = path.resolve()
    cwd = cwd.resolve()
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        target = cwd / "lark_assets" / bucket / _safe_name(path.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_size != path.stat().st_size:
            shutil.copy2(path, target)
        return target.relative_to(cwd).as_posix()


def _set_public(token: str, doc_type: str, cwd: Path, as_identity: str | None = None) -> dict[str, Any]:
    cmd = [
        "lark-cli", "drive", "permission.public", "patch",
        "--token", token,
        "--type", doc_type,
        "--data", json.dumps({"link_share_entity": "anyone_readable", "external_access": True}, ensure_ascii=False),
        "--yes",
        "--format", "json",
    ]
    if as_identity:
        cmd.extend(["--as", as_identity])
    return _run(cmd, cwd=cwd)


def import_slides(pptx: Path, name: str, folder_token: str | None, public_share: bool, cwd: Path) -> dict[str, Any]:
    file_arg = _relative_for_lark(pptx, cwd, "ppt")
    cmd = ["lark-cli", "drive", "+import", "--file", file_arg, "--type", "slides", "--name", name, "--format", "json"]
    if folder_token:
        cmd.extend(["--folder-token", folder_token])
    result = _run(cmd, cwd=cwd)
    token = _find_key(result, {"token", "file_token", "presentation_token"})
    if public_share and token:
        result["public_permission"] = _set_public(token, "slides", cwd)
    return result


def create_base(records: list[dict], name: str, folder_token: str | None, public_share: bool, cwd: Path) -> dict[str, Any]:
    cmd = [
        "lark-cli", "base", "+base-create",
        "--name", name,
        "--table-name", TABLE_NAME,
        "--fields", json.dumps(BASE_FIELDS, ensure_ascii=False),
        "--time-zone", "Asia/Shanghai",
        "--format", "json",
    ]
    if folder_token:
        cmd.extend(["--folder-token", folder_token])
    created = _run(cmd, cwd=cwd)
    base_token = _find_key(created, {"app_token", "base_token", "token"})
    if not base_token:
        raise RuntimeError(f"cannot find base token in lark-cli output: {created}")

    inserted = []
    for r in records:
        fields = {
            "真名": r.get("name", ""),
            "性别": r.get("gender", ""),
            "期望职业": r.get("career", ""),
            "prompt": r.get("prompt", ""),
            "生成状态": r.get("status", ""),
        }
        upsert = _run([
            "lark-cli", "base", "+record-upsert",
            "--base-token", base_token,
            "--table-id", TABLE_NAME,
            "--json", json.dumps(fields, ensure_ascii=False),
            "--format", "json",
        ], cwd=cwd)
        record_id = _find_key(upsert, {"record_id", "id"})
        item = {"record": r, "upsert": upsert}
        inserted.append(item)

    result = {"base": created, "records": inserted}
    if public_share:
        result["public_permission"] = _set_public(base_token, "bitable", cwd)
    return result


def publish(manifest: Path, pptx: Path, name: str, folder_token: str | None, public_share: bool, output: Path) -> dict[str, Any]:
    records = json.loads(manifest.read_text(encoding="utf-8"))
    ok_records = [r for r in records if r.get("status") in {"success", "skipped"}]
    cwd = output.resolve().parent
    cwd.mkdir(parents=True, exist_ok=True)
    result = {
        "base": create_base(ok_records, f"{name} 多维表格", folder_token, public_share, cwd),
        "slides": import_slides(pptx, f"{name} PPT", folder_token, public_share, cwd),
    }
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish kid career portrait artifacts to Lark.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--name", default="儿童未来职业照")
    parser.add_argument("--folder-token", default=None)
    parser.add_argument("--public-share", action="store_true", help="set slides/base to anyone_readable; only use after explicit user confirmation")
    parser.add_argument("--output", default="lark_publish_result.json")
    args = parser.parse_args()
    publish(Path(args.manifest), Path(args.pptx), args.name, args.folder_token, args.public_share, Path(args.output))


if __name__ == "__main__":
    main()
