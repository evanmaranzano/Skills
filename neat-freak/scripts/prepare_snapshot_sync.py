#!/usr/bin/env python3
"""Render changed ~/.agents/memory/*.md into ai-memory snapshot bodies.

Deterministic part of the local -> ai-memory snapshot sync (see
references/local-memory-sync.md). Pushing pages via MCP memory_write_page
and recording the baseline (--mark) stay with the agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

STATE_NAME = ".snapshot-sync-state.json"


def strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return "\n".join(lines[i + 1 :]).lstrip("\n")
    return text


def render(name: str, raw: str) -> tuple[str, str]:
    """Return (title_line_used_for_h1_check, final_body)."""
    body = strip_frontmatter(raw)
    quote = (
        f"> 权威源：{host_label()} `~/.agents/memory/{name}`；"
        f"本页为 {date.today().isoformat()} 导入快照，后续更新以本地为准。"
    )
    first = next((ln for ln in body.splitlines() if ln.strip()), "")
    if first.startswith("# "):
        head, _, rest = body.partition("\n")
        return head, f"{head}\n\n{quote}\n{rest}"
    stem = Path(name).stem
    return f"# {stem}", f"# {stem}\n\n{quote}\n\n{body}"


def host_label() -> str:
    return f"本机（{Path.home().name}）"


def load_state(memory_dir: Path) -> dict:
    p = memory_dir / STATE_NAME
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {"files": {}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--memory-dir", type=Path, default=Path.home() / ".agents" / "memory")
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--mark", action="store_true", help="record current mtimes as synced baseline")
    args = ap.parse_args()

    memory_dir = args.memory_dir
    if not memory_dir.is_dir():
        ap.error(f"memory dir not found: {memory_dir}")

    if args.mark:
        state = {"last_sync": now_iso(), "files": {p.name: p.stat().st_mtime_ns for p in sorted(memory_dir.glob("*.md"))}}
        (memory_dir / STATE_NAME).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"marked {len(state['files'])} files as synced at {state['last_sync']}")
        return 0

    state = load_state(memory_dir)
    prev = state.get("files", {})
    out_dir = args.out_dir or Path.home() / "AppData" / "Local" / "Temp" / "opencode" / "neat-freak-snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    todo = []
    for p in sorted(memory_dir.glob("*.md")):
        mtime = p.stat().st_mtime_ns
        status = "new" if p.name not in prev else ("changed" if prev[p.name] != mtime else "same")
        if status != "same":
            todo.append((p, status))

    if not todo:
        print("all snapshots up to date; nothing to push")
        return 0

    for p, status in todo:
        _, body = render(p.name, p.read_text(encoding="utf-8"))
        (out_dir / p.name).write_text(body, encoding="utf-8")
        print(f"[{status:7}] {p.name} -> local-memory/{p.name}  (body ready: {out_dir / p.name})")

    unchanged = len(list(memory_dir.glob('*.md'))) - len(todo)
    print(f"\n{len(todo)} page(s) to push via memory_write_page, {unchanged} unchanged.")
    print("After all pages verified (read back), run: prepare_snapshot_sync.py --mark")
    return 0


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    sys.exit(main())
