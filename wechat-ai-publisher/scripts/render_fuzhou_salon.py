#!/usr/bin/env python3
"""福州AI技术社区沙龙通稿排版（母版槽位填充）。

原理：第21期通稿的 HTML 清理往期图片与元数据后作为母版，原样提交即可保留版式。
本模块使用母版 templates/fuzhou-ai-salon/master-21.html，
只动三类槽位——段落文字、内容图片 URL、可选二维码；其余结构原样保留，
保证草稿与母版版式一致。

母版结构（21 个顶层子块，字节保持切分）：
    00 文本卡(1段)   01 星标  02 横版主视觉  03 星标  04 现场图
    05 间隔  06 文本卡(1段)  07 星标  08 现场图
    09 间隔  10 文本卡(2段)  11 星标  12 现场图
    13 间隔  14 文本卡(1段)  15 星标  16 现场图
    17 间隔  18 文本卡(2段)  19 间隔  20 文末(二维码+关注语)

文字槽 7 个（块 00/06/10/14/18 内的 <p>），图片槽 5 个（块 02/04/08/12/16）。
段落少于槽：空槽段落删除；整卡空置时连同其前间隔整块删除。
段落多于槽：多余段克隆进最后一个文本卡。
图片少于槽：未用图槽连同其前星标整块删除。
二维码为可选区块；qr_url 缺省或空白时连同专属间隔省略，显式传值时替换。
"""

from __future__ import annotations

import html
import re
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "fuzhou-ai-salon"
MASTER_PATH = TEMPLATE_DIR / "master-21.html"

_SECTION_TAG = re.compile(r"<(/?)(section)([^>]*)>")
_P_RE = re.compile(r"<p[^>]*>[\s\S]*?</p>")
_IMG_RE = re.compile(r"<img[^>]*>")


def _load_master():
    """母版 → (根开标签, 子块列表, 根闭合及之后)。全部字节保持。"""
    content = MASTER_PATH.read_text(encoding="utf-8")
    m = re.match(r"\s*<section[^>]*>", content)
    root_open = content[: m.end()]

    depth = 1
    close_start = None
    for mm in _SECTION_TAG.finditer(content, m.end()):
        if mm.group(1) == "/":
            depth -= 1
            if depth == 0:
                close_start = mm.start()
                break
        else:
            depth += 1
    inner = content[m.end() : close_start]
    tail = content[close_start:]

    spans, depth, start = [], 0, None
    for mm in _SECTION_TAG.finditer(inner):
        if mm.group(1) == "/":
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, mm.end()))
                start = None
        else:
            if depth == 0:
                start = mm.start()
            depth += 1
    chunks = [inner[s:e] for s, e in spans]
    return root_open, chunks, tail


def _is_star_img(tag: str) -> bool:
    return 'data-ratio="1"' in tag and 'data-w="1080"' in tag


def _chunk_kind(chunk: str) -> str:
    if 'data-salon-block="star"' in chunk:
        return "star"
    imgs = _IMG_RE.findall(chunk)
    if imgs:
        return "img"
    for p in _P_RE.findall(chunk):
        if re.sub(r"<[^>]+>|\s", "", p):
            return "text"
    return "spacer"


def _highlight_style(chunks) -> str:
    m = re.search(r'<span textstyle="" style="([^"]+)"', "".join(chunks))
    return m.group(1) if m else "color: rgb(120, 172, 254);font-weight: bold;"


def parse_markdown(md_text: str) -> tuple[list[str], list[str]]:
    """Markdown → (段落列表, 图片路径列表)。**加粗** 映射为母版浅蓝高亮。"""
    paras: list[str] = []
    images: list[str] = []
    pending_h = ""
    for block in re.split(r"\n\s*\n", md_text.strip()):
        block = block.strip()
        if not block:
            continue
        if block.startswith(">"):
            block = re.sub(r"(?m)^\s*>+\s?", "", block).strip()
            if not block:
                continue
        for m in re.finditer(r"!\[.*?\]\((.*?)\)", block):
            images.append(m.group(1).strip())
        text = re.sub(r"!\[.*?\]\(.*?\)", "", block).strip()
        if text.startswith("##"):
            pending_h = re.sub(r"^##+\s*", "", text).strip()
            continue
        if pending_h:
            text = f"**{pending_h}**　{text}"
            pending_h = ""
        if text:
            paras.append(text)
    if pending_h:
        paras.append(f"**{pending_h}**")
    return paras, images


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _inline(text: str, hl: str) -> str:
    out: list[str] = []
    pos = 0
    for m in re.finditer(r"\*\*(.+?)\*\*", text):
        if m.start() > pos:
            out.append(f'<span leaf="">{_esc(text[pos : m.start()])}</span>')
        out.append(
            f'<span leaf=""><span textstyle="" style="{hl}">'
            f"{_esc(m.group(1))}</span></span>"
        )
        pos = m.end()
    if pos < len(text):
        out.append(f'<span leaf="">{_esc(text[pos:])}</span>')
    return "".join(out)


def _fill_p(p_html: str, text: str, hl: str) -> str:
    m = re.match(r"<p[^>]*>", p_html)
    return f"{m.group(0)}{_inline(text, hl)}</p>"


def _set_img_url(tag: str, url: str) -> str:
    tag = re.sub(r'\sdata-croporisrc="[^"]*"', "", tag)
    tag = re.sub(r'\sdata-cropsel[xy][12]="[^"]*"', "", tag)
    tag = re.sub(r'\sdata-imgfileid="[^"]*"', "", tag)
    tag = re.sub(r'\sdata-aistatus="[^"]*"', "", tag)
    url = html.escape(url.strip(), quote=True)
    if re.search(r'data-src="', tag):
        tag = re.sub(r'data-src="[^"]*"', lambda _: f'data-src="{url}"', tag)
    else:
        tag = tag.replace("<img ", f'<img data-src="{url}" ', 1)
    if re.search(r'\ssrc="', tag):
        tag = re.sub(r'\ssrc="[^"]*"', lambda _: f' src="{url}"', tag)
    else:
        tag = tag.replace("<img ", f'<img src="{url}" ', 1)
    return tag


def render(md_text: str, image_urls: list[str], qr_url: str | None = None) -> str:
    paras, md_images = parse_markdown(md_text)
    if not paras:
        raise ValueError("正文没有可用段落")
    images = [
        url.strip()
        for url in (list(image_urls) or md_images)
        if url and url.strip()
    ]

    root_open, chunks, tail = _load_master()
    hl = _highlight_style(chunks)
    kinds = [_chunk_kind(c) for c in chunks]
    footer_i = len(chunks) - 1
    text_idx = [i for i, k in enumerate(kinds) if k == "text"]
    img_idx = [i for i, k in enumerate(kinds) if k == "img" and i != footer_i]

    # ---- 文字槽 ----
    p_slots = [(ci, pi) for ci in text_idx for pi in range(len(_P_RE.findall(chunks[ci])))]
    fill, extras = paras[: len(p_slots)], paras[len(p_slots) :]
    filled: dict[int, dict[int, str]] = {}
    for (ci, pi), text in zip(p_slots, fill):
        filled.setdefault(ci, {})[pi] = text

    last_filled_chunk = max(filled) if filled else None
    for ci in text_idx:
        mapping = filled.get(ci)
        if mapping is None:
            continue
        state = {"pi": 0}

        def sub_p(m, mapping=mapping, state=state):
            pi = state["pi"]
            state["pi"] += 1
            if pi in mapping:
                return _fill_p(m.group(0), mapping[pi], hl)
            return ""

        chunks[ci] = _P_RE.sub(sub_p, chunks[ci])
        if extras and ci == last_filled_chunk:
            last_open = re.match(r"<p[^>]*>", _P_RE.findall(chunks[ci])[-1])
            add = "".join(
                f"{last_open.group(0)}{_inline(t, hl)}</p>" for t in extras
            )
            pos = chunks[ci].rfind("</section>")
            chunks[ci] = chunks[ci][:pos] + add + chunks[ci][pos:]

    dropped_text = {ci for ci in text_idx if ci not in filled}

    # ---- 图片槽 ----
    for ci, url in zip(img_idx, images):
        done = False

        def repl(m, url=url):
            nonlocal done
            if done or _is_star_img(m.group(0)):
                return m.group(0)
            done = True
            return _set_img_url(m.group(0), url)

        chunks[ci] = _IMG_RE.sub(repl, chunks[ci])
    unused_img = set(img_idx[len(images) :])

    # ---- 二维码（缺省时连同前置专属间隔整块省略）----
    qr_url = (qr_url or "").strip()
    dropped_qr = set()
    if qr_url:
        done = False

        def qr_repl(m):
            nonlocal done
            if done:
                return m.group(0)
            done = True
            return _set_img_url(m.group(0), qr_url)

        chunks[footer_i] = _IMG_RE.sub(qr_repl, chunks[footer_i])
    else:
        dropped_qr.add(footer_i)
        if footer_i > 0 and kinds[footer_i - 1] == "spacer":
            dropped_qr.add(footer_i - 1)

    # ---- 组装（含删除规则） ----
    final = []
    for i, ch in enumerate(chunks):
        if i in dropped_text or i in unused_img or i in dropped_qr:
            continue
        if kinds[i] == "spacer" and (i + 1) in dropped_text:
            continue
        if kinds[i] == "star" and (i + 1) in unused_img:
            continue
        final.append(ch)
    return root_open + "".join(final) + tail
