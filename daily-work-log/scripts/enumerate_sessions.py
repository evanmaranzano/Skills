#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enumerate_sessions.py — 扫描本机 opencode / claudecode / kimicode 今日(或指定日)会话清单。

用途：daily-work-log skill 阶段 0/2。ccusage 未装或覆盖不到时的本地兜底；也可独立运行
查看「今天开了哪些会」。

输出：统一 JSON 列表
  [{agent, session_id, title, first_prompt, created_at(iso local), has_content}]

用法：
  python enumerate_sessions.py                 # 今天
  python enumerate_sessions.py --date 2026-08-25
  python enumerate_sessions.py --agents opencode,claudecode,kimicode

依赖：Python 3（sqlite3 / json / pathlib 标准库），无第三方包。
"""
import argparse, datetime, json, os, sqlite3, sys

HOME = os.path.expanduser("~")

# 各工具存储路径（Windows 实测；可被环境变量覆盖）
OPENCODE_DB = os.environ.get("E_OPENCODE_DB", os.path.join(HOME, ".local", "share", "opencode", "opencode.db"))
CLAUDE_PROJECTS = os.environ.get("E_CLAUDE_PROJECTS", os.path.join(HOME, ".claude", "projects"))
KIMI_SESSIONS = os.environ.get("E_KIMI_SESSIONS", os.path.join(HOME, ".kimi-code", "sessions"))


def iso_ms(ms):
    if not ms:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000.0).isoformat(timespec="seconds")
    except Exception:
        return None


def in_day(dt_naive, day):
    return dt_naive.date() == day


def scan_opencode(day):
    out = []
    if not os.path.exists(OPENCODE_DB):
        return out
    try:
        con = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True)
    except Exception as e:
        print(f"[warn] opencode db unreadable: {e}", file=sys.stderr)
        return out
    try:
        rows = con.execute(
            "SELECT id,title,time_created,time_updated FROM session WHERE time_created IS NOT NULL"
        ).fetchall()
    except Exception as e:
        print(f"[warn] opencode query failed: {e}", file=sys.stderr)
        con.close()
        return out
    for sid, title, tc, _tu in rows:
        dt = datetime.datetime.fromtimestamp(int(tc) / 1000.0)
        if dt.date() != day:
            continue
        # 取首条 user 文本
        fp = None
        try:
            parts = con.execute(
                "SELECT data FROM part WHERE session_id=? ORDER BY time_created", (sid,)
            ).fetchall()
            for (data,) in parts:
                try:
                    d = json.loads(data)
                except Exception:
                    continue
                if d.get("type") == "text" and d.get("text"):
                    t = d["text"].strip()
                    # 跳过明显的 agent 自言自语/思考引导（首条 user 通常是标题或短 prompt）
                    if t and not t.startswith(("我", "我来", "先看", "好的", "收到", "I ", "Let me", "Now")):
                        fp = t[:200]
                        break
        except Exception:
            pass
        out.append({
            "agent": "opencode", "session_id": sid,
            "title": title or None, "first_prompt": fp,
            "created_at": dt.isoformat(timespec="seconds"),
            "has_content": bool(fp),
        })
    con.close()
    return out


def scan_claudecode(day):
    out = []
    if not os.path.isdir(CLAUDE_PROJECTS):
        return out
    import re
    for proj in os.listdir(CLAUDE_PROJECTS):
        pdir = os.path.join(CLAUDE_PROJECTS, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, fn)
            m = re.match(r"([0-9a-f-]{36})\.jsonl", fn)
            sid = m.group(1) if m else fn
            fp, created = None, None
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except Exception:
                            continue
                        if o.get("type") == "user" and created is None:
                            ts = o.get("timestamp")
                            if ts:
                                created = ts
                            content = (o.get("message") or {}).get("content")
                            if isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict) and c.get("type") == "text":
                                        fp = c.get("text", "").strip()[:200]
                                        break
                            elif isinstance(content, str):
                                fp = content.strip()[:200]
                        if fp:
                            break
            except Exception as e:
                print(f"[warn] claude read fail {path}: {e}", file=sys.stderr)
            # created 是 RFC3339 UTC
            day_in = False
            if created:
                try:
                    dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                    dt = dt.astimezone()
                except Exception:
                    dt = None
                if dt:
                    day_in = dt.date() == day
                    created_local = dt.isoformat(timespec="seconds")
                else:
                    created_local = None
            if not day_in:
                continue
            out.append({
                "agent": "claudecode", "session_id": sid,
                "title": fp or None, "first_prompt": fp,
                "created_at": created_local,
                "has_content": bool(fp),
            })
    return out


def scan_kimi(day):
    out = []
    if not os.path.isdir(KIMI_SESSIONS):
        return out
    for wd in os.listdir(KIMI_SESSIONS):
        wdpath = os.path.join(KIMI_SESSIONS, wd)
        if not os.path.isdir(wdpath):
            continue
        for item in os.listdir(wdpath):
            sdir = os.path.join(wdpath, item)
            if not (os.path.isdir(sdir) and item.startswith("session_")):
                continue
            st_path = os.path.join(sdir, "state.json")
            if not os.path.exists(st_path):
                continue
            try:
                with open(st_path, "r", encoding="utf-8", errors="replace") as fh:
                    st = json.load(fh)
            except Exception:
                continue
            created = st.get("createdAt")
            dt = datetime.datetime.fromtimestamp(int(created) / 1000.0) if created else None
            if not dt or dt.date() != day:
                continue
            out.append({
                "agent": "kimicode", "session_id": item,
                "title": st.get("title"),
                "first_prompt": (st.get("lastPrompt") or "")[:200],
                "created_at": dt.isoformat(timespec="seconds"),
                "has_content": bool(st.get("title") or st.get("lastPrompt")),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD, default today")
    ap.add_argument("--agents", default="opencode,claudecode,kimicode")
    args = ap.parse_args()

    day = datetime.date.today()
    if args.date:
        day = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()

    want = {a.strip() for a in args.agents.split(",") if a.strip()}
    all_rows = []
    if "opencode" in want:
        all_rows += scan_opencode(day)
    if "claudecode" in want:
        all_rows += scan_claudecode(day)
    if "kimicode" in want:
        all_rows += scan_kimi(day)

    all_rows.sort(key=lambda r: r.get("created_at") or "")
    print(json.dumps(all_rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
