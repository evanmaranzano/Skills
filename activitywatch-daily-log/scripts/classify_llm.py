from datetime import datetime
import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import ROOT, PROCESSED_DIR, dump_json, ensure_dirs, load_json, load_settings, parse_day

CACHE_PATH = ROOT / "config" / "classification_cache.json"
DEFAULT_CACHE_THRESHOLD = 0.8
DEFAULT_LOW_CONF_THRESHOLD = 0.6

# 启发式匹配规则：app 关键词 → (类别, 基础置信度)
HEURISTIC_RULES: dict[str, tuple[str, float]] = {
    # AI 编程
    "claude": ("AI 编程", 0.95),
    "codex": ("AI 编程", 0.95),
    "cursor": ("AI 编程", 0.95),
    "vscode": ("AI 编程", 0.9),
    "visual studio code": ("AI 编程", 0.9),
    "code.exe": ("AI 编程", 0.9),
    "gitpod": ("AI 编程", 0.9),
    "replit": ("AI 编程", 0.9),
    "windsurf": ("AI 编程", 0.9),
    "qoder": ("AI 编程", 0.9),
    "sublime": ("AI 编程", 0.85),
    "intellij": ("AI 编程", 0.9),
    "goland": ("AI 编程", 0.9),
    "pycharm": ("AI 编程", 0.9),
    "dataspell": ("AI 编程", 0.9),
    "android studio": ("AI 编程", 0.9),
    "xcode": ("AI 编程", 0.9),
    "android-studio": ("AI 编程", 0.9),
    # 开发工具
    "powershell": ("开发工具", 0.9),
    "pwsh": ("开发工具", 0.9),
    "cmd": ("开发工具", 0.85),
    "windows terminal": ("开发工具", 0.9),
    "wt.exe": ("开发工具", 0.9),
    "wsl.exe": ("开发工具", 0.9),
    "docker": ("开发工具", 0.9),
    "docker.exe": ("开发工具", 0.9),
    "kitty": ("开发工具", 0.9),
    "iterm": ("开发工具", 0.9),
    "cmder": ("开发工具", 0.9),
    "rust analyzer": ("开发工具", 0.9),
    "nuget": ("开发工具", 0.85),
    "npm": ("开发工具", 0.85),
    "pip": ("开发工具", 0.85),
    "cargo": ("开发工具", 0.85),
    "java": ("开发工具", 0.85),
    "javaw": ("开发工具", 0.85),
    "python": ("开发工具", 0.85),
    "pythonw": ("开发工具", 0.85),
    "node": ("开发工具", 0.85),
    "nodejs": ("开发工具", 0.85),
    "golang": ("开发工具", 0.85),
    "csharp": ("开发工具", 0.85),
    "dotnet": ("开发工具", 0.85),
    # 资料检索
    "chrome": ("资料检索", 0.95),
    "chromium": ("资料检索", 0.95),
    "edge": ("资料检索", 0.95),
    "firefox": ("资料检索", 0.95),
    "brave": ("资料检索", 0.95),
    "safari": ("资料检索", 0.95),
    "opera": ("资料检索", 0.95),
    "yandex": ("资料检索", 0.95),
    "google": ("资料检索", 0.9),
    "bing": ("资料检索", 0.9),
    "baidu": ("资料检索", 0.9),
    "github": ("资料检索", 0.9),
    "stackoverflow": ("资料检索", 0.9),
    "zhihu": ("资料检索", 0.9),
    "v2ex": ("资料检索", 0.9),
    "reddit": ("资料检索", 0.9),
    "wikipedia": ("资料检索", 0.9),
    "youtube": ("资料检索", 0.85),
    "twitch": ("资料检索", 0.85),
    # 沟通
    "wechat": ("沟通", 0.95),
    "weixin": ("沟通", 0.95),
    "wx": ("沟通", 0.9),
    "qq": ("沟通", 0.95),
    "dingtalk": ("沟通", 0.95),
    "telegram": ("沟通", 0.95),
    "discord": ("沟通", 0.95),
    "slack": ("沟通", 0.95),
    "teams": ("沟通", 0.95),
    "outlook": ("沟通", 0.95),
    "gmail": ("沟通", 0.95),
    "mail": ("沟通", 0.85),
    "feishu": ("沟通", 0.95),
    "lark": ("沟通", 0.95),
    "line": ("沟通", 0.9),
    "whatsapp": ("沟通", 0.95),
    "signal": ("沟通", 0.95),
    # 娱乐
    "steam": ("娱乐", 0.95),
    "valorant": ("娱乐", 0.95),
    "delta force": ("娱乐", 0.95),
    "league of legends": ("娱乐", 0.95),
    "csgo": ("娱乐", 0.95),
    "bilibili": ("娱乐", 0.95),
    "netflix": ("娱乐", 0.95),
    "spotify": ("娱乐", 0.95),
    "spotify.exe": ("娱乐", 0.95),
    "epic": ("娱乐", 0.9),
    "origin": ("娱乐", 0.9),
    "battle.net": ("娱乐", 0.9),
    "twitch": ("娱乐", 0.85),
    "网易云音乐": ("娱乐", 0.95),
    "qq音乐": ("娱乐", 0.95),
    # 论文/文档
    "word": ("论文/文档", 0.95),
    "wps": ("论文/文档", 0.95),
    "pdf": ("论文/文档", 0.9),
    "adobe": ("论文/文档", 0.9),
    "zotero": ("论文/文档", 0.95),
    "notion": ("论文/文档", 0.85),
    "obsidian": ("论文/文档", 0.85),
    "onenote": ("论文/文档", 0.9),
    "evernote": ("论文/文档", 0.9),
    "notepad": ("论文/文档", 0.85),
    "notepad.exe": ("论文/文档", 0.85),
    "记事本": ("论文/文档", 0.85),
    # 系统杂项
    "explorer": ("系统杂项", 0.95),
    "explorer.exe": ("系统杂项", 0.95),
    "settings": ("系统杂项", 0.95),
    "system settings": ("系统杂项", 0.95),
    "任务管理器": ("系统杂项", 0.9),
    "task manager": ("系统杂项", 0.9),
    "taskmgr": ("系统杂项", 0.95),
    "taskmgr.exe": ("系统杂项", 0.95),
    "downloads": ("系统杂项", 0.9),
    "7-zip": ("系统杂项", 0.9),
    "winrar": ("系统杂项", 0.9),
    "winrar.exe": ("系统杂项", 0.9),
    "control panel": ("系统杂项", 0.9),
    "控制面板": ("系统杂项", 0.9),
    "searchhost": ("系统杂项", 0.85),
    "lockapp": ("系统杂项", 0.95),
    "lockapp.exe": ("系统杂项", 0.95),
    "ctfmon": ("系统杂项", 0.85),
    "svchost": ("系统杂项", 0.85),
    "csrss": ("系统杂项", 0.85),
    "services": ("系统杂项", 0.85),
    "logonui": ("系统杂项", 0.85),
    "dwm": ("系统杂项", 0.85),
    "runtimebroker": ("系统杂项", 0.85),
    "apphost": ("系统杂项", 0.85),
    "credential": ("系统杂项", 0.85),
    "flow.launcher": ("系统杂项", 0.9),
    "alacritty": ("系统杂项", 0.9),
    "clash": ("系统杂项", 0.85),
    "verge": ("系统杂项", 0.85),
    "ditto": ("系统杂项", 0.9),
    "openwith": ("系统杂项", 0.9),
    "cc-switch": ("系统杂项", 0.85),
    "antigravity": ("AI 编程", 0.9),
    "antigravity_setup": ("系统杂项", 0.9),
    "antigravitytools": ("AI 编程", 0.9),
}


def load_cache() -> dict[str, dict[str, Any]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        data = load_json(CACHE_PATH)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(cache: dict[str, dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    dump_json(CACHE_PATH, cache)


def heuristic_match(item: dict[str, Any]) -> tuple[str, float, str] | None:
    """Try to classify an item using heuristic keyword matching.

    Returns (category, confidence, reason) or None if no match.
    """
    apps = item.get("apps", [])
    if isinstance(apps, list):
        app_names = apps
    else:
        app_names = [str(apps)]
    domains = item.get("domains", [])
    if isinstance(domains, list):
        domain_list = domains
    else:
        domain_list = [str(domains) if domains else ""]
    titles = item.get("sample_titles", [])

    # If all app names are "unknown", try to extract app name from titles
    if all(a.lower() in ("unknown", "") for a in app_names) and titles:
        # Extract the first non-trivial title as potential app name
        for t in titles:
            t_stripped = t.strip()
            if len(t_stripped) > 5 and t_stripped not in ("", "新标签页", "Default Gemini Project"):
                # Check if title looks like an app name or contains one
                app_names.append(t_stripped)
                break

    candidates: list[tuple[str, float, str]] = []

    for app_name in app_names:
        app_lower = app_name.lower()
        if app_lower in ("unknown",):
            continue
        for keyword, (category, base_conf) in HEURISTIC_RULES.items():
            if keyword in app_lower:
                candidates.append((category, base_conf, f"应用名匹配关键词: {keyword}"))

    for domain in domain_list:
        domain_lower = domain.lower()
        if not domain_lower or domain_lower == "":
            continue
        for keyword, (category, base_conf) in HEURISTIC_RULES.items():
            if keyword in domain_lower:
                candidates.append((category, base_conf, f"域名匹配关键词: {keyword}"))

    if candidates:
        # Return highest confidence match
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0]

    return None


def build_classify_prompt(unknown_items: list[dict]) -> str:
    lines = [
        "你是一个应用分类助手。你的任务是将未知的应用/网站分类到预设类别中。",
        "",
        "可用类别（必须从以下选择）：",
        "- AI 编程：AI 编程工具（Claude Code, Codex, Cursor, VS Code, etc.）",
        "- 论文/文档：文档编辑和阅读工具（WPS, Word, PDF, Zotero, etc.）",
        "- 资料检索：搜索引擎和网站浏览（Google, Bing, GitHub, StackOverflow, etc.）",
        "- 沟通：通讯工具（微信, QQ, Telegram, Gmail, 飞书, etc.）",
        "- 娱乐：游戏和视频（Steam, Valorant, Bilibili, YouTube, etc.）",
        "- 系统杂项：系统工具和文件管理（Explorer, Settings, Downloads, etc.）",
        "- 开发工具：IDE 和开发工具（Java, Python, Node.js 等原生应用）",
        "- 其他：无法归入以上类别的",
        "",
        "分类规则：",
        "1. 根据应用名、域名、窗口标题判断分类",
        "2. 每个分类必须包含置信度和理由",
        "3. 置信度范围 0.0-1.0",
        "4. 只输出 JSON 数组，不要输出其他内容",
        "",
        "待分类项目：",
    ]

    for i, item in enumerate(unknown_items):
        lines.append(f"--- 项目 {i} ---")
        lines.append(f"应用: {', '.join(item.get('apps', ['unknown'])[:3])}")
        if item.get("domains"):
            lines.append(f"域名: {', '.join(item['domains'][:5])}")
        if item.get("sample_titles"):
            lines.append(f"窗口标题: {', '.join(item['sample_titles'][:3])}")
        lines.append(f"时长: {item['duration_seconds']:.0f} 秒, 事件数: {item['event_count']}")
        lines.append("")

    lines.append("请返回以下 JSON 格式：")
    lines.append('[{"item_index": 0, "category": "AI 编程", "confidence": 0.85, "reason": "应用名包含 gpt 关键词"}]')
    lines.append("")

    return "\n".join(lines)


def parse_llm_response(response: str) -> list[dict[str, Any]]:
    response = response.strip()
    start = response.find("[")
    end = response.rfind("]") + 1
    json_str = response[start:end] if start >= 0 and end > start else response

    try:
        results = json.loads(json_str)
        return results if isinstance(results, list) else []
    except json.JSONDecodeError:
        return []


def validate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for result in results:
        if not isinstance(result, dict):
            continue
        category = result.get("category", "")
        confidence = result.get("confidence")
        reason = result.get("reason", "")
        item_index = result.get("item_index")
        if not category or confidence is None or item_index is None:
            continue
        try:
            item_index = int(item_index)
            if item_index < 0:
                continue
            confidence = float(confidence)
            if confidence < 0 or confidence > 1:
                continue
        except (ValueError, TypeError):
            continue
        valid.append({
            "item_index": item_index,
            "category": category,
            "confidence": round(confidence, 2),
            "reason": reason,
        })
    return valid


def classify_items(unknown_items: list[dict], llm_command: str, timeout: float = 300) -> list[dict[str, Any]]:
    if not unknown_items:
        return []

    prompt = build_classify_prompt(unknown_items)
    prompt_file_path = _write_prompt_to_temp(prompt)
    result = None

    try:
        # Use shell pipe to avoid Windows command line length limit
        import platform
        if platform.system() == "Windows":
            cmd = f'type "{prompt_file_path}" | {llm_command}'
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=timeout, shell=True,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                _log_llm_error("LLM 调用异常", str(exc))
                return []
        else:
            try:
                argv = [item.strip() for item in shlex.split(llm_command, posix=False)]
                result = subprocess.run(
                    argv, input=prompt, capture_output=True,
                    text=True, encoding="utf-8", errors="replace",
                    timeout=timeout,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                _log_llm_error("LLM 调用异常", str(exc))
                return []
    finally:
        _cleanup_temp(prompt_file_path)

    if result is None:
        return []

    if result.returncode != 0:
        _log_llm_error(f"LLM 命令执行失败（{result.returncode}）", result.stderr)
        return []

    raw_output = result.stdout.strip()
    if not raw_output:
        _log_llm_error("LLM 返回空内容", "")
        return []

    results = parse_llm_response(raw_output)
    valid = validate_results(results)
    print(f"LLM 返回 {len(results)} 条结果，有效 {len(valid)} 条")
    return valid


def _write_prompt_to_temp(prompt: str) -> str | None:
    import tempfile
    fd, path = tempfile.mkstemp(suffix='.txt', prefix='daily_log_')
    try:
        os.write(fd, prompt.encode('utf-8'))
        os.close(fd)
    except OSError:
        if os.path.exists(path):
            os.unlink(path)
        return None
    return path


def _cleanup_temp(path: str | None) -> None:
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _log_llm_error(msg: str, detail: str) -> None:
    print(f"ℹ️ {msg}: {detail}", file=sys.stderr)


def apply_cache(unknown_items: list[dict], cache: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    known_results = []
    still_unknown = []

    for item in unknown_items:
        app = item.get("apps", ["unknown"])
        if isinstance(app, list):
            app_str = app[0] if app else "unknown"
        else:
            app_str = str(app)
        domain = item.get("domains", [])
        if isinstance(domain, list):
            domain_str = domain[0] if domain else ""
        else:
            domain_str = str(domain) if domain else ""
        key = f"{app_str}|{domain_str}"

        if key in cache:
            cached = cache[key]
            if cached.get("confidence", 0) >= DEFAULT_CACHE_THRESHOLD:
                known_results.append({
                    "item_index": item.get("_index", 0),
                    "category": cached["category"],
                    "confidence": cached["confidence"],
                    "reason": cached.get("reason", ""),
                })
                continue

        still_unknown.append(item)

    return known_results, still_unknown


def classify_day(day_text: str | None, retry_count: int = 2, allow_llm: bool = True, skip_llm: bool = False) -> int:
    """Two-stage classification: heuristic → cache → LLM.

    1. Heuristic matching (keyword rules)
    2. Cache lookup (>= 0.8)
    3. LLM classification for remaining unknowns
    """
    ensure_dirs()
    target_day = parse_day(day_text)
    summary_path = PROCESSED_DIR / f"{target_day.isoformat()}.summary.json"
    if not summary_path.exists():
        print(f"找不到聚合数据文件：{summary_path}", file=sys.stderr)
        return 1

    summary = load_json(summary_path)
    settings = load_settings()
    cache = load_cache()

    llm_settings = settings.get("llm", {})
    llm_enabled = bool(llm_settings.get("enabled", False)) and allow_llm and not skip_llm
    llm_command = str(llm_settings.get("command", "")) if llm_enabled else ""
    timeout = float(llm_settings.get("timeout_seconds", 300))

    aggregated = summary.get("aggregated", [])

    # Stage 1: Heuristic matching
    heuristic_results = []
    remaining_unknowns = []
    for i, item in enumerate(aggregated):
        item["_index"] = i
        category = item.get("category", "")
        if category and category != "未分类":
            # Already classified
            continue

        heuristic = heuristic_match(item)
        if heuristic:
            cat, conf, reason = heuristic
            item["category"] = cat
            item["confidence"] = conf
            item["classify_reason"] = f"[启发式规则] {reason}"
            heuristic_results.append({
                "item_index": i,
                "category": cat,
                "confidence": conf,
                "reason": reason,
            })
            # Cache for future use
            apps = item.get("apps", [])
            app_str = apps[0] if isinstance(apps, list) and apps else str(apps)
            domain_str = item.get("domains", [])[0] if isinstance(item.get("domains"), list) and item.get("domains") else ""
            cache_key = f"{app_str}|{domain_str}"
            if conf >= DEFAULT_CACHE_THRESHOLD:
                cache[cache_key] = {
                    "category": cat,
                    "confidence": conf,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat(),
                    "reviewed": False,
                }
        else:
            remaining_unknowns.append(item)

    print(f"启发式匹配命中 {len(heuristic_results)} 个，剩余 {len(remaining_unknowns)} 个待分类")

    # Stage 2: Cache lookup
    known_results, still_unknown = apply_cache(remaining_unknowns, cache)
    print(f"缓存命中 {len(known_results)} 个，剩余 {len(still_unknown)} 个需 LLM 分类")

    # Stage 3: LLM classification
    # Map LLM response index (0-based in still_unknown) → _index in aggregated
    unknown_index_map = {i: item.get("_index", i) for i, item in enumerate(still_unknown)}
    llm_results = []
    if llm_command:
        for attempt in range(retry_count):
            if not still_unknown:
                break
            print(f"LLM 分类调用（第 {attempt + 1} 次）...")
            results = classify_items(still_unknown, llm_command, timeout)
            # Remap item_index from local to global
            for r in results:
                local_idx = r.get("item_index")
                if local_idx is not None and local_idx in unknown_index_map:
                    r["item_index"] = unknown_index_map[local_idx]
            llm_results.extend(results)
            if results:
                still_unknown = []
            else:
                print(f"第 {attempt + 1} 次 LLM 调用失败，重试...")
    elif still_unknown:
        reason = "agent 模式" if skip_llm else "LLM 未启用"
        print(f"LLM 分类已跳过（{reason}），剩余 {len(still_unknown)} 个未分类项")

    # Update aggregated data
    updated_items = list(aggregated)
    for result in heuristic_results + known_results + llm_results:
        idx = result.get("item_index")
        if idx is not None and 0 <= idx < len(updated_items):
            updated_items[idx]["category"] = result["category"]
            updated_items[idx]["confidence"] = result["confidence"]
            updated_items[idx]["classify_reason"] = result.get("reason", "")

            if result["confidence"] >= DEFAULT_CACHE_THRESHOLD:
                item = updated_items[idx]
                apps = item.get("apps", [])
                app_str = apps[0] if isinstance(apps, list) and apps else str(apps)
                domain_str = item.get("domains", [])[0] if isinstance(item.get("domains"), list) and item.get("domains") else ""
                cache_key = f"{app_str}|{domain_str}"
                cache[cache_key] = {
                    "category": result["category"],
                    "confidence": result["confidence"],
                    "reason": result.get("reason", ""),
                    "timestamp": datetime.now().isoformat(),
                    "reviewed": False,
                }

    # Low confidence check
    all_results = heuristic_results + known_results + llm_results
    low_conf_items = [r for r in all_results if r["confidence"] < DEFAULT_LOW_CONF_THRESHOLD]
    if low_conf_items:
        print(f"低置信度结果 {len(low_conf_items)} 个，已标记待审核")
        for item in low_conf_items:
            idx = item.get("item_index")
            if idx is not None and 0 <= idx < len(updated_items):
                updated_items[idx]["needs_review"] = True

    summary["aggregated"] = updated_items
    dump_json(summary_path, summary)
    save_cache(cache)

    print(f"启发式: {len(heuristic_results)} | 缓存: {len(known_results)} | LLM: {len(llm_results)}")
    print(f"缓存记录: {len(cache)} 条")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="day_text", help="日期，格式 YYYY-MM-DD")
    args = parser.parse_args()
    return classify_day(args.day_text)


if __name__ == "__main__":
    raise SystemExit(main())
