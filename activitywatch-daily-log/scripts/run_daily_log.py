from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

from common import PROCESSED_DIR, PROMPTS_DIR, REPORTS_DIR, dump_json, ensure_dirs, load_json, load_settings, parse_day
from export_activitywatch import export_day
from aggregate import aggregate_day


def extract_html(text: str) -> str:
    """Extract HTML from LLM response."""
    lowered = text.lower()
    doctype_index = lowered.find("<!doctype html")
    html_index = lowered.find("<html")
    start_index = -1
    if doctype_index >= 0:
        start_index = doctype_index
    elif html_index >= 0:
        start_index = html_index
    if start_index < 0:
        return ""

    end_index = lowered.rfind("</html>")
    if end_index < 0:
        return ""
    end_index += len("</html>")
    return text[start_index:end_index].strip()


class LlmHtmlSafetyParser(HTMLParser):
    """HTML safety checker to prevent XSS attacks."""

    blocked_tags = {"iframe", "object", "embed", "link", "base"}
    resource_attrs = {"src", "href", "action", "poster"}

    def __init__(self) -> None:
        super().__init__()
        self.safe = True
        self._in_style = False
        self._in_script = False
        self._script_buffer = ""

    def check(self, html_text: str) -> bool:
        """Check if HTML is safe."""
        try:
            self.feed(html_text)
            return self.safe
        except Exception:
            return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered_tag = tag.lower()
        if lowered_tag in self.blocked_tags:
            self.safe = False
            return
        if lowered_tag == "style":
            self._in_style = True
        if lowered_tag == "script":
            self._in_script = True
            self._script_buffer = ""

        for name, value in attrs:
            lowered_name = name.lower()
            lowered_value = (value or "").strip().lower()
            if lowered_name.startswith("on"):
                self.safe = False
                return
            if lowered_name in self.resource_attrs and (
                lowered_value.startswith(("http://", "https://", "//", "javascript:", "data:"))
            ):
                self.safe = False
                return
            if lowered_name == "style" and ("url(" in lowered_value or "@import" in lowered_value):
                self.safe = False
                return

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self._in_style = False
        if tag.lower() == "script":
            self._in_script = False
            self._validate_script(self._script_buffer)

    def handle_data(self, data: str) -> None:
        if self._in_style:
            lowered = data.lower()
            if "url(" in lowered or "@import" in lowered:
                self.safe = False
        if self._in_script:
            self._script_buffer += data


    def _validate_script(self, code: str) -> None:
        """Allow only DOM animation scripts (IntersectionObserver)."""
        import re as _re
        lowered = _re.sub(r'\s', '', code.lower())
        dangerous = [
            "fetch(", "xmlhttprequest", ".ajax(",
            "document.cookie", "localstorage",
            "window.open", "window.location",
            ".innerhtml", "document.write",
            "settimeout(", "setinterval(",
        ]
        for pattern in dangerous:
            if pattern in lowered:
                self.safe = False
                return
        for pattern in dangerous:
            if pattern in lowered:
                self.safe = False
                return


def is_safe_llm_html(html_text: str) -> bool:
    """Check if LLM-generated HTML is safe."""
    parser = LlmHtmlSafetyParser()
    return parser.check(html_text)


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def build_llm_argv(llm_command: str, prompt_path: Path, prompt_text: str) -> list[str]:
    """Build LLM argv with optional prompt placeholders."""
    argv = [_strip_wrapping_quotes(item) for item in shlex.split(llm_command, posix=False)]
    if not argv:
        return []

    expanded: list[str] = []

    for item in argv:
        if "{prompt_file}" in item:
            item = item.replace("{prompt_file}", str(prompt_path))
        if "{prompt}" in item:
            item = item.replace("{prompt}", prompt_text)
        expanded.append(item)

    return expanded


def run_llm(
    prompt_text: str,
    prompt_path: Path,
    llm_command: str,
    timeout_seconds: float = 300,
) -> tuple[bool, str]:
    """Run LLM to generate HTML report.

    Returns (success, html_or_error).
    Uses stdin to pass prompt to avoid Windows command line length limit.
    """
    if not llm_command:
        return False, "未配置 LLM 命令"

    # Build command with stdin redirect
    # We prepend 'type' on Windows to pipe file content to stdin
    import platform
    if platform.system() == "Windows":
        if "{prompt}" in llm_command or "{prompt_file}" in llm_command:
            argv = build_llm_argv(llm_command, prompt_path, prompt_text)
            try:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                return False, f"LLM 命令超过 {timeout_seconds:g} 秒未返回"
        else:
            import tempfile
            fd, temp_path = tempfile.mkstemp(suffix='.txt', prefix='daily_log_prompt_')
            try:
                os.write(fd, prompt_text.encode('utf-8'))
                os.close(fd)

                full_cmd = f'type "{temp_path}" | {llm_command}'
                try:
                    result = subprocess.run(
                        full_cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=timeout_seconds,
                        shell=True,
                    )
                except subprocess.TimeoutExpired:
                    return False, f"LLM 命令超过 {timeout_seconds:g} 秒未返回"
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    else:
        if "{prompt}" in llm_command or "{prompt_file}" in llm_command:
            argv = build_llm_argv(llm_command, prompt_path, prompt_text)
            run_kwargs = {"input": None}
        else:
            argv = [_strip_wrapping_quotes(item) for item in shlex.split(llm_command, posix=False)]
            run_kwargs = {"input": prompt_text}
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                **run_kwargs,
            )
        except subprocess.TimeoutExpired:
            return False, f"LLM 命令超过 {timeout_seconds:g} 秒未返回"

    if result.returncode != 0:
        return False, f"LLM 命令执行失败（{result.returncode}）"

    raw_output = result.stdout.strip()
    if not raw_output:
        return False, "LLM 返回空内容"

    html_output = extract_html(raw_output)
    if not html_output:
        return False, "LLM 返回内容不是完整 HTML"

    if not is_safe_llm_html(html_output):
        return False, "LLM 返回 HTML 包含不安全内容"

    return True, html_output


def render_base_html(summary: dict, timeline: list[dict]) -> str:
    """Render basic HTML report as fallback."""
    from datetime import timedelta

    def seconds_to_hm(seconds: float) -> str:
        total_minutes = int(round(seconds / 60))
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}h {minutes:02d}m"

    import html as html_mod

    # If summary has 'aggregated' but no 'categories', derive categories from aggregated data
    categories_payload = summary.get("categories", None)
    if not categories_payload and "aggregated" in summary:
        # Derive categories from aggregated items
        cat_seconds = {}
        cat_weights = {}
        for item in summary.get("aggregated", []):
            cat = item.get("category", "未分类") or "未分类"
            dur = item.get("duration_seconds", 0)
            conf = item.get("confidence", 0) or 0.5
            cat_seconds[cat] = cat_seconds.get(cat, 0) + dur
            cat_weights[cat] = cat_weights.get(cat, 0) + dur * conf
        categories_payload = [
            {"name": c, "seconds": round(d, 2), "confidence": round(cat_weights[c] / d, 2) if d else 0}
            for c, d in sorted(cat_seconds.items(), key=lambda x: x[1], reverse=True)
        ]

    category_rows = "".join(
        f"<tr><td>{html_mod.escape(item['name'])}</td><td>{seconds_to_hm(item['seconds'])}</td><td>{item.get('confidence', 'N/A')}</td></tr>"
        for item in (categories_payload or [])
    )

    # Derive top apps/sites from aggregated data
    app_durations: dict[str, float] = {}
    site_durations: dict[str, float] = {}
    for item in summary.get("aggregated", []):
        dur = item.get("duration_seconds", 0)
        for app in item.get("apps", []):
            app_durations[app] = app_durations.get(app, 0) + dur
        for domain in item.get("domains", []):
            if domain:
                site_durations[domain] = site_durations.get(domain, 0) + dur
    top_apps = sorted(app_durations.items(), key=lambda x: x[1], reverse=True)[:10]
    top_sites = sorted(site_durations.items(), key=lambda x: x[1], reverse=True)[:10]

    app_rows = "".join(
        f"<tr><td>{html_mod.escape(name)}</td><td>{seconds_to_hm(dur)}</td></tr>"
        for name, dur in top_apps
    )
    site_rows = "".join(
        f"<tr><td>{html_mod.escape(name)}</td><td>{seconds_to_hm(dur)}</td></tr>"
        for name, dur in top_sites
    )
    timeline_items = "".join(
        "<article class='item'>"
        f"<div class='time'>{html_mod.escape(item.get('start', ''))} - {html_mod.escape(item.get('end', ''))}</div>"
        f"<h3>{html_mod.escape(item.get('category', ''))}</h3>"
        f"<p>{html_mod.escape(item.get('summary_hint', ''))}</p>"
        f"<div class='meta'>证据: {html_mod.escape(', '.join(item.get('evidence', [])))} | 置信度: {item.get('confidence', 'N/A')}</div>"
        "</article>"
        for item in timeline[:30]
    )

    date_str = summary.get("date", "unknown")
    active_hm = seconds_to_hm(summary.get("active_seconds", 0))
    afk_hm = seconds_to_hm(summary.get("afk_seconds", 0))
    timeline_count = summary.get("timeline_block_count", 0)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{date_str} 日报</title>
  <style>
    :root {{
      --bg:#f4f7fb; --card:#ffffff; --text:#172033; --muted:#5b6477; --line:#dbe3ef;
      --brand:#14532d; --accent:#0f766e; --warn:#b45309;
    }}
    body {{ margin:0; font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:linear-gradient(180deg,#edf6f3 0%, #f8fafc 100%); color:var(--text); }}
    .wrap {{ max-width:1100px; margin:0 auto; padding:28px 18px 60px; }}
    .hero {{ background:linear-gradient(135deg,#123524,#0f766e); color:#fff; border-radius:24px; padding:28px; }}
    .hero h1 {{ margin:0 0 10px; font-size:34px; }}
    .hero p {{ margin:0; color:#d9fbe8; }}
    .grid {{ display:grid; gap:16px; grid-template-columns:repeat(3,minmax(0,1fr)); margin-top:20px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:20px; padding:20px; box-shadow:0 10px 24px rgba(15,23,42,.05); }}
    h2 {{ margin:30px 0 12px; font-size:24px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px 8px; text-align:left; }}
    th {{ color:var(--muted); font-size:13px; }}
    .metric {{ font-size:28px; font-weight:700; }}
    .muted {{ color:var(--muted); }}
    .item {{ border:1px solid var(--line); border-radius:16px; padding:14px 16px; margin:10px 0; background:#fff; }}
    .time {{ color:var(--accent); font-weight:700; margin-bottom:6px; }}
    .meta {{ color:var(--muted); font-size:13px; }}
    @media (max-width:860px) {{ .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <h1>{date_str} 活动日报</h1>
      <p>基础版自动日报。当前内容基于 ActivityWatch 本地活动数据与规则分类生成。</p>
    </section>

    <section class="grid">
      <div class="card">
        <div class="metric">{active_hm}</div>
        <div class="muted">活跃总时长</div>
      </div>
      <div class="card">
        <div class="metric">{afk_hm}</div>
        <div class="muted">AFK 总时长</div>
      </div>
      <div class="card">
        <div class="metric">{timeline_count}</div>
        <div class="muted">活动片段数</div>
      </div>
    </section>

    <section class="card">
      <h2>活动类别</h2>
      <table>
        <thead><tr><th>类别</th><th>时长</th><th>平均置信度</th></tr></thead>
        <tbody>{category_rows}</tbody>
      </table>
    </section>

    <section class="grid">
      <div class="card">
        <h2>Top 应用</h2>
        <table>
          <thead><tr><th>应用</th><th>时长</th></tr></thead>
          <tbody>{app_rows}</tbody>
        </table>
      </div>
      <div class="card">
        <h2>Top 网站</h2>
        <table>
          <thead><tr><th>站点</th><th>时长</th></tr></thead>
          <tbody>{site_rows}</tbody>
        </table>
      </div>
      <div class="card">
        <h2>数据可信度说明</h2>
        <p class="muted">这是一版规则分类日报，不会编造未出现在原始日志中的活动。浏览器标签、窗口标题缺失时，判断置信度会下降。</p>
      </div>
    </section>

    <section class="card">
      <h2>时间线复盘</h2>
      {timeline_items}
    </section>
  </main>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", dest="day_text", help="日期，格式 YYYY-MM-DD")
    parser.add_argument("--skip-llm", action="store_true", help="只生成基础 HTML，不调用 LLM")
    parser.add_argument("--llm-command", default="", help="外部 LLM CLI 命令")
    parser.add_argument("--use-sample", action="store_true", help="使用示例数据")
    parser.add_argument("--agent-mode", action="store_true", help="只输出结构化 JSON，由外部 agent 生成 HTML")
    args = parser.parse_args()

    ensure_dirs()
    target_day = parse_day(args.day_text)
    day_value = target_day.isoformat()
    settings = load_settings()

    # In agent-mode, redirect stdout to stderr so only JSON goes to stdout
    _original_stdout = sys.stdout
    if args.agent_mode:
        sys.stdout = sys.stderr

    # Step 1: Export data
    try:
        code = export_day(day_value, use_sample=args.use_sample)
    except Exception as exc:
        print(f"导出 ActivityWatch 数据失败：{exc}", file=sys.stderr)
        return 1
    if code != 0:
        print("导出 ActivityWatch 数据失败，流程中止。", file=sys.stderr)
        return code
    print("✅ 数据导出完成")

    # Step 2: Aggregate data
    try:
        code = aggregate_day(day_value)
    except Exception as exc:
        print(f"数据聚合失败：{exc}", file=sys.stderr)
        return 1
    if code != 0:
        print("数据聚合失败，流程中止。", file=sys.stderr)
        return code
    print("✅ 数据聚合完成")

    # Step 3: Merge AI tool sessions (AI-digest data)
    try:
        print("🤖 合并 AI 工具会话数据...")
        from merge_ai_sessions import (
            collect_claude_code,
            collect_antigravity,
            collect_codex,
            collect_gemini_cli,
            merge_ai_sessions as merge_ai,
        )
        all_sessions = []
        all_sessions.extend(collect_claude_code(target_day))
        all_sessions.extend(collect_antigravity(target_day))
        all_sessions.extend(collect_codex(target_day))
        all_sessions.extend(collect_gemini_cli(target_day))
        print(f"  收集到 {len(all_sessions)} 个 AI 会话")
        summary_path = PROCESSED_DIR / f"{day_value}.summary.json"
        summary = load_json(summary_path)
        merge_ai(summary, all_sessions)
        dump_json(summary_path, summary)
        print("✅ AI 工具会话数据已合并")
    except Exception as exc:
        print(f"⚠️ 合并 AI 会话数据异常：{exc}", file=sys.stderr)

    # Step 4: Classify unknown items via LLM (optional, can be skipped if no unknown)
    try:
        # Try to import classify_llm
        try:
            from classify_llm import classify_day as llm_classify_day
            print("🤖 开始 LLM 分类...")
            code = llm_classify_day(day_value, allow_llm=not args.skip_llm, skip_llm=args.agent_mode)
            if code == 0:
                print("✅ LLM 分类完成")
            else:
                print("⚠️ LLM 分类失败，继续使用基础数据")
        except ImportError:
            print("ℹ️ classify_llm 模块不可用，跳过 LLM 分类")
    except Exception as exc:
        print(f"LLM 分类异常：{exc}", file=sys.stderr)

    # Agent mode: output structured JSON and exit
    if args.agent_mode:
        return _output_agent_json(day_value, _original_stdout)

    # Step 4: Build HTML generation prompt
    try:
        from build_prompt_v2 import build_html_prompt as build_html_prompt_v2
        print("📝 构建 LLM prompt...")
        code = build_html_prompt_v2(day_value)
        if code != 0:
            print("构建 prompt 失败，流程中止。", file=sys.stderr)
            return code
        print("✅ LLM prompt 构建完成")
    except Exception as exc:
        print(f"构建 prompt 失败：{exc}", file=sys.stderr)
        return 1

    # Step 5: Generate HTML
    report_path = REPORTS_DIR / f"{day_value}.html"

    if args.skip_llm:
        print("已按要求跳过 LLM 调用。")
        code = _render_fallback_html(day_value, report_path)
        if code != 0:
            return code
        print(f"已生成基础 HTML：{report_path}")
        return 0

    llm_command = resolve_llm_command(args.llm_command, settings)
    if not llm_command:
        print("未提供 LLM 命令，尝试生成基础 HTML。")
        code = _render_fallback_html(day_value, report_path)
        if code != 0:
            return code
        print(f"已生成基础 HTML：{report_path}")
        return 0

    # Retry loop for LLM
    prompt_path = PROMPTS_DIR / f"{day_value}.prompt.txt"
    timeout_seconds = float(settings.get("llm", {}).get("timeout_seconds", 300))
    llm_success = False
    llm_error = ""

    for attempt in range(2):
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8")
            success, result = run_llm(prompt_text, prompt_path, llm_command, timeout_seconds)
            if success:
                report_path.write_text(result, encoding="utf-8")
                print(f"✅ 已生成 AI 增强版 HTML：{report_path}")
                llm_success = True
                break
            else:
                llm_error = result
                print(f"第 {attempt + 1} 次 LLM 调用失败：{llm_error}")
        except Exception as exc:
            llm_error = str(exc)
            print(f"第 {attempt + 1} 次 LLM 调用异常：{llm_error}")

    if not llm_success:
        print("⚠️ LLM 生成失败，fallback 到基础版 HTML。")
        code = _render_fallback_html(day_value, report_path)
        if code != 0:
            return code
        print(f"已生成基础 HTML：{report_path}")

    return 0


def resolve_llm_command(cli_command: str, settings: dict) -> str:
    if cli_command:
        return cli_command
    llm_settings = settings.get("llm", {})
    if not llm_settings.get("enabled", False):
        return ""
    return str(llm_settings.get("command", ""))


def _output_agent_json(day_value: str, original_stdout: object = None) -> int:
    """Output structured JSON for agent-mode HTML generation."""
    summary_path = PROCESSED_DIR / f"{day_value}.summary.json"
    if not summary_path.exists():
        print(f"找不到聚合数据文件：{summary_path}", file=sys.stderr)
        return 1

    summary = load_json(summary_path)
    timeline_path = PROCESSED_DIR / f"{day_value}.timeline.json"
    timeline = []
    if timeline_path.exists():
        try:
            loaded_timeline = load_json(timeline_path)
            if isinstance(loaded_timeline, list):
                timeline = loaded_timeline
        except Exception:
            timeline = []

    unclassified = sum(
        1 for item in summary.get("aggregated", [])
        if not item.get("category") or item.get("category") == "未分类"
    )

    agent_payload = {
        "date": day_value,
        "summary": summary,
        "timeline": timeline,
        "ai_sessions": summary.get("ai_sessions", []),
        "design_system": str(PROMPTS_DIR / "html_gen_prompt.md"),
        "output_path": str(REPORTS_DIR / f"{day_value}.html"),
        "vault_path": str(Path("F:/My-Obsidian-Vault/10-Daily") / f"{day_value}.md"),
        "unclassified_count": unclassified,
    }

    # Restore stdout for JSON output
    if original_stdout is not None:
        sys.stdout = original_stdout
    print(json.dumps(agent_payload, ensure_ascii=False, indent=2))
    return 0


def _render_fallback_html(day_value: str, report_path: Path) -> int:
    """Render fallback HTML from summary data using the inline renderer."""
    summary_path = PROCESSED_DIR / f"{day_value}.summary.json"
    if not summary_path.exists():
        print(f"找不到聚合数据文件：{summary_path}", file=sys.stderr)
        return 1
    summary = load_json(summary_path)
    timeline_path = PROCESSED_DIR / f"{day_value}.timeline.json"
    timeline = []
    if timeline_path.exists():
        loaded_timeline = load_json(timeline_path)
        if isinstance(loaded_timeline, list):
            timeline = loaded_timeline
    html_content = render_base_html(summary, timeline)
    report_path.write_text(html_content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
