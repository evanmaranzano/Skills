#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enumerate_sessions.py — 扫描本机 8 个 agent harness 的今日(或指定日)会话清单。

覆盖：opencode / claudecode / kimicode / zcode / pi / dsh / codex / gemini
（grok 已配置但本机无 CLI、无本地会话落盘，扫描时给出提示后跳过。）

用途：daily-work-log skill 阶段 0/2。ccusage 未装或覆盖不到时的本地兜底；也可独立运行
查看「今天开了哪些会」。

输出：统一 JSON 列表
  [{agent, session_id, title, first_prompt, created_at(iso local), directory, has_content}]

用法：
  python enumerate_sessions.py                 # 今天
  python enumerate_sessions.py --date 2026-09-02
  python enumerate_sessions.py --agents opencode,codex,gemini

安全边界：只读（SQLite 以 mode=ro 打开、会话文件只读）；无网络、无子进程、无动态执行；
不读取任何凭据文件（auth.json / oauth_creds.json / config.toml 等）；first_prompt 截断
200 字符，缩小敏感串外泄面。

依赖：Python 3 标准库；dsh 需要 zstandard（`pip install zstandard`，缺失时自动跳过并提示）。
"""
import argparse
import datetime
import io
import json
import os
import re
import sqlite3
import sys

HOME = os.path.expanduser("~")

# 各工具存储路径（Windows 实测；可被环境变量覆盖）
OPENCODE_DB = os.environ.get("E_OPENCODE_DB", os.path.join(HOME, ".local", "share", "opencode", "opencode.db"))
CLAUDE_PROJECTS = os.environ.get("E_CLAUDE_PROJECTS", os.path.join(HOME, ".claude", "projects"))
KIMI_SESSIONS = os.environ.get("E_KIMI_SESSIONS", os.path.join(HOME, ".kimi-code", "sessions"))
ZCODE_DB = os.environ.get("E_ZCODE_DB", os.path.join(HOME, ".zcode", "cli", "db", "db.sqlite"))
PI_SESSIONS = os.environ.get("E_PI_SESSIONS", os.path.join(HOME, ".pi", "agent", "sessions"))
DSH_SESSIONS = os.environ.get("E_DSH_SESSIONS", os.path.join(HOME, ".dsh", "sessions"))
CODEX_SESSIONS = os.environ.get("E_CODEX_SESSIONS", os.path.join(HOME, ".codex", "sessions"))
CODEX_ARCHIVED = os.environ.get("E_CODEX_ARCHIVED", os.path.join(HOME, ".codex", "archived_sessions"))
CODEX_INDEX = os.environ.get("E_CODEX_INDEX", os.path.join(HOME, ".codex", "session_index.jsonl"))
GEMINI_TMP = os.environ.get("E_GEMINI_TMP", os.path.join(HOME, ".gemini", "tmp"))
GROK_HOME = os.environ.get("E_GROK_HOME", os.path.join(HOME, ".grok"))

PROMPT_SNIPPET_LEN = 200          # first_prompt 截断长度
MAX_DECOMP_LINES = 200_000        # zstd 解压行数上限（防解压炸弹 / 异常大文件）
MAX_JSONL_LINES = 5_000           # 找首条 user prompt 的最大扫描行数
MAX_CHAT_JSON_BYTES = 32 * 1024 * 1024
MAX_INDEX_BYTES = 64 * 1024 * 1024

try:
    import zstandard as zstd
    HAS_ZSTD = True
except Exception:
    HAS_ZSTD = False


def day_bounds(day):
    """目标日本地 00:00 与次日 00:00（本地时区）。"""
    start = datetime.datetime.combine(day, datetime.time.min)
    return start, start + datetime.timedelta(days=1)


def iso_ms(ms):
    if not ms:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000.0).isoformat(timespec="seconds")
    except Exception:
        return None


def iso_utc(ts_str):
    """RFC3339 UTC 字符串 → 本地 ISO。失败返回 None。"""
    if not ts_str:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts_str).replace("Z", "+00:00")).astimezone().isoformat(timespec="seconds")
    except Exception:
        return None


def mtime_at_or_after(path, day_start_dt):
    """文件 mtime 是否落在目标日当天或之后（做预过滤：今天创建/写过的文件才值得解析）。"""
    try:
        return datetime.datetime.fromtimestamp(os.stat(path).st_mtime) >= day_start_dt
    except OSError:
        return False


# 首条 prompt 的噪声前缀（agent 自言自语/系统注入，非真实 user 输入）。
# 注意别放裸 "我" / "I "：真实用户 prompt 常以它们开头。
NOISE_PREFIXES = ("我来", "我先", "先看", "好的", "收到", "让我", "Let me", "Now ", "<")


def looks_real(text):
    t = (text or "").lstrip()
    return bool(t) and not t.startswith(NOISE_PREFIXES)


# 凭据脱敏：first_prompt/title 进日志前抹掉密钥形态的串（实测会话里出现过
# "设置环境变量 XXX_API_KEY 为 sk-…"，原文直出会把 key 带进飞书）。
# 注意：Python 正则把 CJK 也算 \w，"为sk-" 之间没有 \b，必须用 ASCII lookbehind。
SECRET_REDACTERS = [
    (re.compile(r"(?i)(?<![A-Za-z0-9])(api[_-]?key|apikey|token|secret|password|passwd|pwd|authorization)(?![A-Za-z0-9])(\s*[:=]\s*)\S+"),
     r"\1\2***"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]{3,}){1,2}"), "eyJ***"),  # JWT（含全部段）
    (re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{6,}"), "sk-***"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}"), "Bearer ***"),
]


def redact(text):
    if not text:
        return text
    for pat, repl in SECRET_REDACTERS:
        text = pat.sub(repl, text)
    return text


def snippet(text):
    return redact(text.strip()[:PROMPT_SNIPPET_LEN]) if text else None


def row(agent, sid, title, fp, created_at, directory=None):
    return {
        "agent": agent,
        "session_id": sid,
        "title": redact(title) if title else None,
        "first_prompt": fp,
        "created_at": created_at,
        "directory": directory,
        "has_content": bool(fp),
    }


def scan_opencode(day):
    out = []
    if not os.path.exists(OPENCODE_DB):
        return out
    try:
        con = sqlite3.connect(f"file:{OPENCODE_DB}?mode=ro", uri=True)
    except Exception as e:
        print(f"[warn] opencode db unreadable: {e}", file=sys.stderr)
        return out
    start_ms, end_ms = day_bounds(day)[0].timestamp() * 1000, day_bounds(day)[1].timestamp() * 1000
    try:
        rows = con.execute(
            "SELECT id,title,time_created,directory FROM session "
            "WHERE time_created IS NOT NULL AND time_created >= ? AND time_created < ?",
            (start_ms, end_ms),
        ).fetchall()
    except Exception as e:
        print(f"[warn] opencode query failed: {e}", file=sys.stderr)
        con.close()
        return out
    for sid, title, tc, directory in rows:
        dt = datetime.datetime.fromtimestamp(int(tc) / 1000.0)
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
                if d.get("type") == "text" and d.get("text") and looks_real(d["text"]):
                    fp = snippet(d["text"])
                    break
        except Exception:
            pass
        out.append(row("opencode", sid, title or None, fp, dt.isoformat(timespec="seconds"), directory))
    con.close()
    return out


def scan_zcode(day):
    """ZCode CLI：~/.zcode/cli/db/db.sqlite。真实 user prompt 在 message(role=user,
    semantics.kind=user_prompt) 关联的 text part 里。"""
    out = []
    if not os.path.exists(ZCODE_DB):
        return out
    try:
        con = sqlite3.connect(f"file:{ZCODE_DB}?mode=ro", uri=True)
    except Exception as e:
        print(f"[warn] zcode db unreadable: {e}", file=sys.stderr)
        return out
    start_ms, end_ms = day_bounds(day)[0].timestamp() * 1000, day_bounds(day)[1].timestamp() * 1000
    try:
        rows = con.execute(
            "SELECT id,title,time_created,directory FROM session "
            "WHERE time_created IS NOT NULL AND time_created >= ? AND time_created < ?",
            (start_ms, end_ms),
        ).fetchall()
    except Exception as e:
        print(f"[warn] zcode query failed: {e}", file=sys.stderr)
        con.close()
        return out
    for sid, title, tc, directory in rows:
        dt = datetime.datetime.fromtimestamp(int(tc) / 1000.0)
        fp = None
        try:
            rows2 = con.execute(
                """SELECT m.data, p.data FROM part p
                   JOIN message m ON p.message_id = m.id
                   WHERE m.session_id=? ORDER BY m.time_created, p.time_created""",
                (sid,),
            ).fetchall()
            for mdata, pdata in rows2:
                try:
                    md = json.loads(mdata)
                    pd = json.loads(pdata)
                except Exception:
                    continue
                if md.get("role") != "user":
                    continue
                if pd.get("type") == "text" and pd.get("text") and looks_real(pd["text"]):
                    fp = snippet(pd["text"])
                    break
        except Exception:
            pass
        out.append(row("zcode", sid, title or None, fp, dt.isoformat(timespec="seconds"), directory))
    con.close()
    return out


def scan_claudecode(day):
    """Claude Code：~/.claude/projects/<project>/<uuid>.jsonl，type==user 行的
    message.content[].text 是用户输入，timestamp 为 RFC3339 UTC。"""
    out = []
    if not os.path.isdir(CLAUDE_PROJECTS):
        return out
    day_start, _ = day_bounds(day)
    for proj in os.listdir(CLAUDE_PROJECTS):
        pdir = os.path.join(CLAUDE_PROJECTS, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, fn)
            if not mtime_at_or_after(path, day_start):
                continue
            m = re.match(r"([0-9a-f-]{36})\.jsonl", fn)
            sid = m.group(1) if m else fn
            fp, created = None, None
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh):
                        if i >= MAX_JSONL_LINES:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except Exception:
                            continue
                        if o.get("type") != "user":
                            continue
                        ts = o.get("timestamp")
                        if ts and not created:
                            created = ts
                        content = (o.get("message") or {}).get("content")
                        texts = []
                        if isinstance(content, list):
                            texts = [c.get("text", "") for c in content
                                     if isinstance(c, dict) and c.get("type") == "text"]
                        elif isinstance(content, str):
                            texts = [content]
                        for t in texts:
                            if looks_real(t):
                                fp = snippet(t)
                                break
                        if fp:
                            break
            except Exception as e:
                print(f"[warn] claude read fail {path}: {e}", file=sys.stderr)
                continue
            created_local = iso_utc(created)
            if created_local and datetime.datetime.fromisoformat(created_local).date() == day:
                out.append(row("claudecode", sid, fp, fp, created_local))
    return out


def scan_kimi(day):
    """Kimi Code：~/.kimi-code/sessions/<wd>_<hash>/session_<uuid>/，state.json 含
    title / lastPrompt / createdAt(RFC3339 UTC 或毫秒)。"""
    out = []
    if not os.path.isdir(KIMI_SESSIONS):
        return out
    day_start, _ = day_bounds(day)
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
            # state.json 的 mtime 就是最后写入时间；早于目标日直接跳过
            if not mtime_at_or_after(st_path, day_start):
                continue
            try:
                with open(st_path, "r", encoding="utf-8", errors="replace") as fh:
                    st = json.load(fh)
            except Exception:
                continue
            created = st.get("createdAt")
            dt = None
            if created:
                try:
                    dt = datetime.datetime.fromtimestamp(int(created) / 1000.0)
                except (ValueError, TypeError, OverflowError, OSError):
                    dt = None
            if dt is None:
                iso = iso_utc(created)
                if iso:
                    dt = datetime.datetime.fromisoformat(iso)
            if not dt or dt.date() != day:
                continue
            lp = snippet(st.get("lastPrompt"))
            out.append(row("kimicode", item, st.get("title"), lp, dt.isoformat(timespec="seconds")))
    return out


def scan_pi(day):
    """Pi：~/.pi/agent/sessions/<项目目录>/<时间戳>_<uuid>.jsonl。首行 type==session 含
    RFC3339 UTC timestamp 与 cwd；type==message 且 message.role==user 的 text 是 prompt。"""
    out = []
    if not os.path.isdir(PI_SESSIONS):
        return out
    day_start, _ = day_bounds(day)
    for proj in sorted(os.listdir(PI_SESSIONS)):
        pdir = os.path.join(PI_SESSIONS, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, fn)
            if not mtime_at_or_after(path, day_start):
                continue
            fp, created, sid, cwd = None, None, None, None
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh):
                        if i >= MAX_JSONL_LINES:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            o = json.loads(line)
                        except Exception:
                            continue
                        t = o.get("type")
                        if t == "session":
                            sid = o.get("id") or fn
                            created = o.get("timestamp") or created
                            cwd = o.get("cwd")
                            continue
                        if t == "message" and fp is None:
                            m = o.get("message") or {}
                            if m.get("role") == "user":
                                content = m.get("content") or []
                                if isinstance(content, list):
                                    for c in content:
                                        if isinstance(c, dict) and c.get("type") == "text" and c.get("text") and looks_real(c["text"]):
                                            fp = snippet(c["text"])
                                            break
                                elif isinstance(content, str) and looks_real(content):
                                    fp = snippet(content)
                            if fp:
                                break
            except Exception as e:
                print(f"[warn] pi read fail {path}: {e}", file=sys.stderr)
                continue
            created_local = iso_utc(created)
            if created_local and datetime.datetime.fromisoformat(created_local).date() == day:
                out.append(row("pi", sid or fn, fp, fp, created_local, cwd))
    return out


def scan_dsh(day):
    """DeepSeek Harness：~/.dsh/sessions/<项目目录>/session-<uuid>/session.jsonl.zstd。
    真实用户输入是 type==user/message 且 data.source.kind==user（系统注入的
    system-reminder 无此标记）。流式解压 + 行数上限，找到首条即停。"""
    out = []
    if not os.path.isdir(DSH_SESSIONS):
        return out
    if not HAS_ZSTD:
        print("[warn] dsh skipped: zstandard 未安装（pip install zstandard）", file=sys.stderr)
        return out
    day_start, _ = day_bounds(day)
    for proj in sorted(os.listdir(DSH_SESSIONS)):
        pdir = os.path.join(DSH_SESSIONS, proj)
        if not os.path.isdir(pdir):
            continue
        for item in sorted(os.listdir(pdir)):
            sdir = os.path.join(pdir, item)
            if not (os.path.isdir(sdir) and item.startswith("session-")):
                continue
            zpath = os.path.join(sdir, "session.jsonl.zstd")
            if not os.path.exists(zpath):
                continue
            if not mtime_at_or_after(zpath, day_start):
                continue
            created, fp, cwd = None, None, None
            try:
                with open(zpath, "rb") as fh:
                    reader = zstd.ZstdDecompressor().stream_reader(fh)
                    with io.TextIOWrapper(reader, encoding="utf-8", errors="replace") as text:
                        for i, line in enumerate(text):
                            if i >= MAX_DECOMP_LINES:
                                break
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                o = json.loads(line)
                            except Exception:
                                continue
                            t = o.get("type")
                            if t == "session":
                                created = o.get("createdAt") or created
                                cwd = o.get("cwd")
                                continue
                            if t == "user/message" and fp is None:
                                data = o.get("data") or {}
                                src = data.get("source") or {}
                                if src.get("kind") != "user" and data.get("role") != "user":
                                    continue  # 系统注入的 reminder，非真实用户输入
                                content = data.get("content") or []
                                if isinstance(content, list):
                                    for c in content:
                                        if isinstance(c, dict) and c.get("type") == "text" and c.get("text") and looks_real(c["text"]):
                                            fp = snippet(c["text"])
                                            break
                                elif isinstance(content, str) and looks_real(content):
                                    fp = snippet(content)
                            if fp:
                                break
            except Exception as e:
                print(f"[warn] dsh read fail {zpath}: {e}", file=sys.stderr)
                continue
            created_local = iso_ms(created)
            if created_local and datetime.datetime.fromisoformat(created_local).date() == day:
                out.append(row("dsh", item, fp, fp, created_local, cwd))
    return out


CODEX_ROLLOUT_RE = re.compile(r"^rollout-(\d{4}-\d{2}-\d{2})T\d{2}-\d{2}-\d{2}-([0-9a-f-]{36})\.jsonl$")
# 注入上下文：XML 形态（<recommended_plugins> / <user_instructions> / <environment_context>）
# 和 markdown 形态（"# AGENTS.md instructions" 回放）都要跳过。
CODEX_INJECT_RE = re.compile(
    r"^(<[a-zA-Z_]|#\s*(AGENTS\.md|user instructions|instructions|environment))", re.IGNORECASE
)


def _codex_index_titles():
    """session_index.jsonl: {id, thread_name, updated_at}，id 后写覆盖前写。文件异常大则放弃。"""
    titles = {}
    try:
        if os.path.getsize(CODEX_INDEX) > MAX_INDEX_BYTES:
            return titles
        with open(CODEX_INDEX, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("id") and o.get("thread_name"):
                    titles[o["id"]] = o["thread_name"]
    except OSError:
        pass
    return titles


def _codex_first_prompt(path):
    """rollout jsonl 的首条真实 user 输入。跳过注入的 <xxx> 上下文与 event 事件；
    response_item(message/role=user) 与 event_msg(user_message) 都认。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= MAX_JSONL_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t, pl = o.get("type"), (o.get("payload") or {})
                if t == "response_item" and pl.get("type") == "message" and pl.get("role") == "user":
                    for c in pl.get("content") or []:
                        if isinstance(c, dict) and c.get("type") in ("input_text", "text"):
                            txt = c.get("text", "")
                            if txt.strip() and not CODEX_INJECT_RE.match(txt.lstrip()) and looks_real(txt):
                                return snippet(txt)
                elif t == "event_msg" and pl.get("type") == "user_message":
                    txt = pl.get("message") or ""
                    if txt.strip() and not CODEX_INJECT_RE.match(txt.lstrip()) and looks_real(txt):
                        return snippet(txt)
    except Exception as e:
        print(f"[warn] codex read fail {path}: {e}", file=sys.stderr)
    return None


def scan_codex(day):
    """Codex CLI：~/.codex/sessions/YYYY/MM/DD/rollout-<本地时间戳>-<uuid>.jsonl（文件名是
    本地时间；首行 session_meta 的 timestamp 是 RFC3339 UTC）。archived_sessions/ 一并扫。
    用户消息：response_item(message/role=user) 或 event_msg(user_message)，
    注入的 <recommended_plugins> / <user_instructions> / <environment_context> 必须跳过。"""
    out = []
    if not os.path.isdir(CODEX_SESSIONS):
        return out
    titles = _codex_index_titles()
    day_start, _ = day_bounds(day)
    candidates = []
    year_root = os.path.join(CODEX_SESSIONS, str(day.year))
    day_dir = os.path.join(year_root, f"{day.month:02d}", f"{day.day:02d}")
    if os.path.isdir(day_dir):
        candidates += [os.path.join(day_dir, f) for f in os.listdir(day_dir)]
    if os.path.isdir(CODEX_ARCHIVED):
        candidates += [os.path.join(CODEX_ARCHIVED, f) for f in os.listdir(CODEX_ARCHIVED)]
    seen = set()
    for path in candidates:
        fn = os.path.basename(path)
        m = CODEX_ROLLOUT_RE.match(fn)
        if not m or path in seen:
            continue
        seen.add(path)
        file_day = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").date()
        # 会话可能跨午夜：文件名日期在目标日 ±1 天内才值得解析
        if abs((file_day - day).days) > 1:
            continue
        if not mtime_at_or_after(path, day_start - datetime.timedelta(days=1)):
            continue
        meta_id, meta_created, meta_cwd = None, None, None
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
                    if o.get("type") == "session_meta":
                        pl = o.get("payload") or {}
                        meta_id = pl.get("session_id") or pl.get("id")
                        meta_created = o.get("timestamp") or pl.get("timestamp")
                        meta_cwd = pl.get("cwd")
                        break
        except Exception as e:
            print(f"[warn] codex meta fail {path}: {e}", file=sys.stderr)
        created_local = iso_utc(meta_created) or f"{file_day.isoformat()}T00:00:00"
        if datetime.datetime.fromisoformat(created_local).date() != day:
            continue
        fp = _codex_first_prompt(path)
        title = titles.get(meta_id or "") or titles.get(m.group(2)) or None
        out.append(row("codex", meta_id or m.group(2), title, fp, created_local, meta_cwd))
    return out


def scan_gemini(day):
    """Gemini CLI：~/.gemini/tmp/<项目hash>/chats/session-<时间戳>-<hash>.json。
    顶层 {sessionId, projectHash, startTime(RFC3339 UTC), lastUpdated, messages[]}；
    messages[].type=='user' 时 content(str) 是用户输入（assistant 的 type=='gemini'）。"""
    out = []
    if not os.path.isdir(GEMINI_TMP):
        return out
    day_start, _ = day_bounds(day)
    for proj in os.listdir(GEMINI_TMP):
        chats = os.path.join(GEMINI_TMP, proj, "chats")
        if not os.path.isdir(chats):
            continue
        for fn in os.listdir(chats):
            if not (fn.startswith("session-") and fn.endswith(".json")):
                continue
            path = os.path.join(chats, fn)
            if not mtime_at_or_after(path, day_start):
                continue
            try:
                if os.path.getsize(path) > MAX_CHAT_JSON_BYTES:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    d = json.load(fh)
            except Exception as e:
                print(f"[warn] gemini read fail {path}: {e}", file=sys.stderr)
                continue
            created_local = iso_utc(d.get("startTime"))
            if not created_local or datetime.datetime.fromisoformat(created_local).date() != day:
                continue
            fp = None
            for m in d.get("messages") or []:
                if isinstance(m, dict) and m.get("type") == "user":
                    c = m.get("content")
                    if isinstance(c, str) and looks_real(c):
                        fp = snippet(c)
                        break
            out.append(row("gemini", d.get("sessionId") or fn, fp, fp, created_local))
    return out


def scan_grok(day):
    """Grok CLI：本机 ~/.grok/ 只有 config.toml（且 CLI 未安装），会话不落盘，无法扫描。
    保留占位让 --agents grok 不至于静默无输出。"""
    if os.path.isdir(GROK_HOME):
        print("[warn] grok skipped: 本机无 Grok CLI/无本地会话落盘（~/.grok 仅配置），无法枚举", file=sys.stderr)
    return []


SCANNERS = {
    "opencode": scan_opencode,
    "claudecode": scan_claudecode,
    "kimicode": scan_kimi,
    "zcode": scan_zcode,
    "pi": scan_pi,
    "dsh": scan_dsh,
    "codex": scan_codex,
    "gemini": scan_gemini,
    "grok": scan_grok,
}


def main():
    # GBK 控制台下 print CJK/emoji 会 UnicodeEncodeError，输出统一走 UTF-8
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="扫描本机各 agent harness 指定日期的会话清单（只读）")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD, default today")
    ap.add_argument("--agents", default=",".join(k for k in SCANNERS if k != "grok"),
                    help="逗号分隔，可选: " + ",".join(SCANNERS))
    args = ap.parse_args()

    day = datetime.date.today()
    if args.date:
        day = datetime.datetime.strptime(args.date, "%Y-%m-%d").date()

    want = {a.strip() for a in args.agents.split(",") if a.strip()}
    unknown = want - set(SCANNERS)
    if unknown:
        print(f"[warn] 未知 agent（忽略）: {', '.join(sorted(unknown))}", file=sys.stderr)
        want -= unknown

    all_rows = []
    for name, fn in SCANNERS.items():
        if name in want:
            all_rows += fn(day)

    all_rows.sort(key=lambda r: r.get("created_at") or "")
    print(json.dumps(all_rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
