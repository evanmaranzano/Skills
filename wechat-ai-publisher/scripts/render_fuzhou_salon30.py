#!/usr/bin/env python3
"""亲子活动（智汇对谈第30期版式）公众号排版（salon30 积木母版渲染）。

基于智汇对谈第30期公开文章版式提取的可复用结构积木（templates/fuzhou-ai-salon/master-30.html），
适用于亲子活动回顾，与现有 `salon`（技术沙龙通稿，master-21.html）并存，不替换既有默认行为；
不自动套用技术沙龙固定结尾、期数或活动事实。

Markdown 槽位约定：
- 首个 `# 标题` 及紧随其后的连续导语行（至空行/图片/`##` 为止）→ 居中开篇导语块；
  `# 标题` 渲染为浅蓝白字徽标，导语中 `**加粗**` 渲染为浅蓝加粗，`==标签==` 亦渲染为浅蓝白字徽标。
- `## 章节标题` → `Part.N` 桃色角标 + 蓝色圆角标题横幅（自动递增 Part.1, Part.2, ...，不限制 4 个）。
- `### 小节标题` → `01` / `02` 蓝色半圆编号 + 渐变胶囊子标题（每个 Part 内自动从 01 递增）。
- 正文段落 / 引用 / 列表 → 合并入浅蓝底正文卡（`rgba(96, 160, 246, 0.18)`，首行缩进 2em）。
- `![alt](url)` → 按出现顺序渲染为全宽图片卡（省略未用图片槽，不保留任何原文图片或视频/名片）。
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "fuzhou-ai-salon"
MASTER_PATH = TEMPLATE_DIR / "master-30.html"

_SECTION_TAG = re.compile(r"<(/?)(section)\b([^>]*)>", re.IGNORECASE)
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)>\s]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.+)$")


def _load_master_blocks(master_path: Path = MASTER_PATH) -> dict[str, str]:
    """从 master-30.html 按 data-salon30-block 抽取各个可复用积木 HTML。"""
    content = master_path.read_text(encoding="utf-8")
    blocks: dict[str, str] = {}
    marker = re.compile(r'<section\b[^>]*data-salon30-block="([^"]+)"[^>]*>')
    pos = 0
    while True:
        m = marker.search(content, pos)
        if not m:
            break
        name = m.group(1)
        depth = 1
        close_start = None
        close_end = None
        for tag in _SECTION_TAG.finditer(content, m.end()):
            if tag.group(1) == "/":
                depth -= 1
                if depth == 0:
                    close_start = tag.start()
                    close_end = tag.end()
                    break
            else:
                depth += 1
        if close_start is None or close_end is None:
            raise ValueError(f"master-30.html 积木 {name!r} 缺少闭合 </section>")
        blocks[name] = content[m.end() : close_start].strip()
        pos = close_end

    required = {"root", "intro", "image", "body_card", "part_header", "sub_header", "divider"}
    missing = required - blocks.keys()
    if missing:
        raise ValueError(f"master-30.html 缺少必要积木：{sorted(missing)}")
    return blocks


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _esc_attr(text: str) -> str:
    return html.escape(text, quote=True)


def _inline_intro(text: str) -> str:
    """渲染居中导语行内标记：**重点** 为浅蓝加粗，==徽标== 为浅蓝底白字。"""
    token_re = re.compile(r"==(.+?)==|\*\*(.+?)\*\*")
    out: list[str] = []
    pos = 0
    for m in token_re.finditer(text):
        if m.start() > pos:
            out.append(
                f'<span style="text-indent: 0em; box-sizing: border-box;">'
                f'<span leaf="">{_esc(text[pos : m.start()])}</span></span>'
            )
        if m.group(1) is not None:
            out.append(
                f'<span style="display: inline-block; padding: 1px 8px; '
                f'color: rgb(255, 255, 255); background-color: rgb(134, 190, 237); '
                f'box-sizing: border-box;"><strong style="box-sizing: border-box;">'
                f'<span leaf="">{_esc(m.group(1))}</span></strong></span>'
            )
        else:
            out.append(
                f'<span style="color: rgb(134, 190, 237); box-sizing: border-box;">'
                f'<strong style="box-sizing: border-box;">'
                f'<span leaf="">{_esc(m.group(2))}</span></strong></span>'
            )
        pos = m.end()
    if pos < len(text):
        out.append(
            f'<span style="text-indent: 0em; box-sizing: border-box;">'
            f'<span leaf="">{_esc(text[pos:])}</span></span>'
        )
    return "".join(out)


def _inline_body(text: str) -> str:
    """渲染正文卡行内标记：**加粗** 为深蓝加粗，`代码` 为浅蓝胶囊。"""
    token_re = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`")
    out: list[str] = []
    pos = 0
    for m in token_re.finditer(text):
        if m.start() > pos:
            out.append(f'<span leaf="">{_esc(text[pos : m.start()])}</span>')
        if m.group(1) is not None:
            out.append(
                f'<strong style="color: rgb(47, 118, 204); box-sizing: border-box;">'
                f'<span leaf="">{_esc(m.group(1))}</span></strong>'
            )
        else:
            out.append(
                f'<code style="padding: 1px 5px; background: rgba(81, 156, 240, 0.14); '
                f'border-radius: 3px; color: rgb(47, 118, 204); '
                f'font-family: Consolas, Monaco, monospace; font-size: 13px;">'
                f'{_esc(m.group(2))}</code>'
            )
        pos = m.end()
    if pos < len(text):
        out.append(f'<span leaf="">{_esc(text[pos:])}</span>')
    return "".join(out)


def _strip_frontmatter(md_text: str) -> str:
    return re.sub(r"^---\r?\n.*?\r?\n---\r?\n?", "", md_text.lstrip("﻿"), count=1, flags=re.DOTALL)


def _strip_part_prefix(title: str) -> str:
    cleaned = re.sub(r"^part\.?\s*\d+\s*[:：.\-—]*\s*", "", title, flags=re.IGNORECASE).strip()
    return cleaned or title.strip()


def _strip_sub_prefix(title: str) -> str:
    cleaned = re.sub(r"^\d{1,2}(?:\s*[.、:：\-—]+\s*|\s+)", "", title).strip()
    return cleaned or title.strip()


def _parse_blocks(md_text: str) -> list[dict]:
    """将 Markdown 解析为按出现顺序排列的 salon30 积木指令流。"""
    text = _strip_frontmatter(md_text).strip()
    if not text:
        return []

    lines = text.splitlines()
    blocks: list[dict] = []
    body_items: list[dict] = []
    seen_intro = False
    i = 0

    def flush_body() -> None:
        nonlocal body_items
        if body_items:
            blocks.append({"type": "body_card", "items": body_items})
            body_items = []

    def append_text_with_images(raw_lines: list[str], kind: str = "paragraph") -> None:
        """保留段落内嵌图片的位置顺序，拆分为正文与图片块。"""
        buf: list[str] = []

        def flush_buf() -> None:
            joined = " ".join(s.strip() for s in buf if s.strip()).strip()
            buf.clear()
            if joined:
                body_items.append({"kind": kind, "text": joined})

        for line in raw_lines:
            pos = 0
            found = False
            for m in _MD_IMAGE_RE.finditer(line):
                found = True
                before = line[pos : m.start()].strip()
                if before:
                    buf.append(before)
                flush_buf()
                flush_body()
                blocks.append({
                    "type": "image",
                    "alt": m.group(1).strip() or "图片",
                    "url": m.group(2).strip(),
                })
                pos = m.end()
            after = line[pos:].strip() if found else line.strip()
            if after:
                buf.append(after)
        flush_buf()

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue

        h_match = _HEADING_RE.match(stripped)
        if h_match:
            level = len(h_match.group(1))
            title = h_match.group(2).strip()
            if level == 1 and not seen_intro and not blocks and not body_items:
                seen_intro = True
                intro_lines: list[dict] = [{"badge": True, "text": title}]
                i += 1
                while i < len(lines):
                    nxt = lines[i].strip()
                    if not nxt or _HEADING_RE.match(nxt) or _MD_IMAGE_RE.search(nxt):
                        break
                    if nxt.startswith(">"):
                        nxt = re.sub(r"^>+\s*", "", nxt).strip()
                    if nxt:
                        intro_lines.append({"badge": False, "text": nxt})
                    i += 1
                blocks.append({"type": "intro", "lines": intro_lines})
                continue

            flush_body()
            if level == 1:
                body_items.append({"kind": "paragraph", "text": f"**{title}**"})
            elif level == 2:
                blocks.append({"type": "part_header", "title": _strip_part_prefix(title)})
            else:
                blocks.append({"type": "sub_header", "title": _strip_sub_prefix(title)})
            i += 1
            continue

        # 引用块
        if stripped.startswith(">"):
            q_lines: list[str] = []
            while i < len(lines):
                cur = lines[i].strip()
                if not cur or not cur.startswith(">"):
                    break
                cleaned = re.sub(r"^>+\s?", "", cur).strip()
                if cleaned:
                    q_lines.append(cleaned)
                i += 1
            append_text_with_images(q_lines, kind="quote")
            continue

        # 列表项（按条渲染，避免合并成单行破坏阅读层次）
        list_m = _LIST_ITEM_RE.match(stripped)
        if list_m:
            while i < len(lines):
                cur = lines[i].strip()
                lm = _LIST_ITEM_RE.match(cur)
                if not lm:
                    break
                prefix = "• " if cur[0] in "-*+" else cur[: cur.find(" ") + 1]
                item_text = lm.group(1).strip()
                if _MD_IMAGE_RE.search(item_text):
                    append_text_with_images([prefix + item_text], kind="list")
                else:
                    body_items.append({"kind": "list", "text": prefix + item_text})
                i += 1
            continue

        # 普通段落（收集至空行、标题、引用或列表）
        para_lines: list[str] = []
        while i < len(lines):
            cur = lines[i].strip()
            if not cur or _HEADING_RE.match(cur) or cur.startswith(">") or _LIST_ITEM_RE.match(cur):
                break
            para_lines.append(cur)
            i += 1
        append_text_with_images(para_lines, kind="paragraph")

    flush_body()
    return blocks


def parse_markdown(md_text: str) -> tuple[list[str], list[str]]:
    """兼容 run_pipeline.py 预检接口：返回 (可用段落列表, 图片路径列表)。"""
    blocks = _parse_blocks(md_text)
    paras: list[str] = []
    images: list[str] = []
    for blk in blocks:
        btype = blk["type"]
        if btype == "intro":
            paras.extend(line["text"] for line in blk["lines"] if line["text"].strip())
        elif btype == "body_card":
            paras.extend(item["text"] for item in blk["items"] if item["text"].strip())
        elif btype in ("part_header", "sub_header"):
            if blk["title"].strip():
                paras.append(blk["title"])
        elif btype == "image":
            images.append(blk["url"])
    return paras, images


def _render_intro(template: str, lines: list[dict]) -> str:
    p_html: list[str] = []
    for line in lines:
        if line["badge"]:
            inner = (
                f'<span style="display: inline-block; padding: 1px 8px; '
                f'color: rgb(255, 255, 255); background-color: rgb(134, 190, 237); '
                f'box-sizing: border-box;"><strong style="box-sizing: border-box;">'
                f'<span leaf="">{_esc(line["text"])}</span></strong></span>'
            )
        else:
            inner = _inline_intro(line["text"])
        p_html.append(
            f'<p style="margin: 0px 0px 4px; padding: 0px; box-sizing: border-box; visibility: visible;">'
            f'{inner}</p>'
        )
    return template.replace("{{INTRO_PARAGRAPHS}}", "".join(p_html))


def _render_body_card(template: str, items: list[dict]) -> str:
    p_html: list[str] = []
    last_idx = len(items) - 1
    for idx, item in enumerate(items):
        mb = "0px" if idx == last_idx else "8px"
        if item["kind"] == "list":
            style = (
                f"white-space: normal; margin: 0px 0px {mb}; padding: 0px; "
                "box-sizing: border-box; text-indent: 0em; visibility: visible;"
            )
        elif item["kind"] == "quote":
            style = (
                f"white-space: normal; margin: 0px 0px {mb}; padding: 2px 0px 2px 10px; "
                "border-left: 3px solid rgb(81, 156, 240); box-sizing: border-box; "
                "text-indent: 0em; visibility: visible;"
            )
        else:
            style = (
                f"white-space: normal; margin: 0px 0px {mb}; padding: 0px; "
                "box-sizing: border-box; text-indent: 2em; visibility: visible;"
            )
        p_html.append(f'<p style="{style}">{_inline_body(item["text"])}</p>')
    return template.replace("{{BODY_PARAGRAPHS}}", "".join(p_html))


def render(md_text: str, image_urls: list[str] | None = None) -> str:
    """将 Markdown 渲染为 salon30 微信公众号 HTML。"""
    blocks = _parse_blocks(md_text)
    has_text = any(b["type"] != "image" for b in blocks)
    if not has_text:
        raise ValueError("正文没有可用段落")

    tpl = _load_master_blocks()
    override_urls = list(image_urls) if image_urls is not None and len(image_urls) > 0 else None

    rendered: list[str] = []
    part_num = 0
    sub_num = 0
    img_idx = 0

    for blk in blocks:
        btype = blk["type"]
        if btype == "intro":
            rendered.append(_render_intro(tpl["intro"], blk["lines"]))
        elif btype == "body_card":
            rendered.append(_render_body_card(tpl["body_card"], blk["items"]))
        elif btype == "part_header":
            part_num += 1
            sub_num = 0
            chunk = tpl["part_header"].replace("{{PART_LABEL}}", f"Part.{part_num}")
            chunk = chunk.replace("{{PART_TITLE}}", _esc(blk["title"]))
            rendered.append(chunk)
        elif btype == "sub_header":
            sub_num += 1
            chunk = tpl["sub_header"].replace("{{SUB_NUM}}", f"{sub_num:02d}")
            chunk = chunk.replace("{{SUB_TITLE}}", _esc(blk["title"]))
            rendered.append(chunk)
        elif btype == "image":
            if override_urls is not None:
                if img_idx >= len(override_urls):
                    continue
                url = override_urls[img_idx]
            else:
                url = blk["url"]
            img_idx += 1
            chunk = tpl["image"].replace("{{IMAGE_URL}}", _esc_attr(url))
            chunk = chunk.replace("{{IMAGE_ALT}}", _esc_attr(blk["alt"]))
            rendered.append(chunk)

    rendered.append(tpl["divider"])
    return tpl["root"].replace("{{BLOCKS}}", "".join(rendered))


def wrap_preview_html(body_html: str, title: str = "亲子活动（salon30）本地排版预览") -> str:
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<meta name="referrer" content="no-referrer">\n'
        f"<title>{_esc(title)}</title>\n"
        "</head>\n"
        '<body style="margin: 0 auto; max-width: 677px; background: #ffffff; padding: 12px 0;">\n'
        f"{body_html}\n"
        "</body>\n</html>\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="渲染亲子活动（salon30，智汇对谈第30期版式）公众号 HTML")
    parser.add_argument("--input", "-i", required=True, help="输入 Markdown 文件")
    parser.add_argument("--output", "-o", required=True, help="输出 HTML 文件")
    parser.add_argument("--preview", action="store_true", help="输出带 UTF-8 与 viewport 的完整 HTML 预览页")
    args = parser.parse_args()

    md_text = Path(args.input).read_text(encoding="utf-8")
    rendered = render(md_text)
    if args.preview:
        rendered = wrap_preview_html(rendered)
    Path(args.output).write_text(rendered, encoding="utf-8")
    print(f"✅ salon30 渲染完成：{args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
