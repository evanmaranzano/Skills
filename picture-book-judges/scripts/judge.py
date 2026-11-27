#!/usr/bin/env python3
"""Children's AI picture book judge helper (offline 3D award ceremony + CSV summary).

Workflow:
    1. Discovery mode (when <output>/scores.json does not exist):
       python judge.py --input <zip_or_folder> --output <dir>
       Scans submissions (subfolders, .zip, or top-level StPageFlip .html books),
       extracts full story text and images without byte-truncation, writes lightweight
       review thumbnails + contact sheets under <output>/review-assets/, writes
       <output>/manifest.json, and prints a concise summary + scores.json template.

    2. Render mode (when <output>/scores.json exists):
       python judge.py --input <zip_or_folder> --output <dir> [options]
       Normalizes scores, distributes entries evenly via snake draft (or honors manual
       winnerIds), builds self-contained offline <output>/index.html, normalized
       <output>/scores.json, and Excel-ready UTF-8 BOM <output>/awards-summary.csv.
"""

from __future__ import annotations

import argparse
import base64
import csv
import html as html_lib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from PIL import Image, ImageDraw, ImageFont

DIMENSIONS = [
    "故事结构与完整性",
    "画面表现与角色一致性",
    "创意想象力",
    "图文契合度",
    "完成度与细节",
]

DEFAULT_AWARD_TITLES = ["最佳故事奖", "最佳画面奖", "最佳创意奖"]

DEFAULT_AWARDS = [
    {"id": "best-story", "title": "最佳故事奖", "icon": "book", "theme": "purple"},
    {"id": "best-art", "title": "最佳画面奖", "icon": "palette", "theme": "coral"},
    {"id": "best-creativity", "title": "最佳创意奖", "icon": "sparkles", "theme": "teal"},
]

DEFAULT_EVENT_LABEL = "摩力AI亲子公益沙龙 · 第七期《空白谜案》"
DEFAULT_PAGE_TITLE = "小小绘本创作家"
DEFAULT_PAGE_SUBTITLE = "AI绘本作品颁奖典礼"

FALLBACK_STRENGTHS = [
    ["故事起承转合完整，小主角的冒险节奏很吸引人", "主角形象前后保持稳定，色彩氛围温暖协调", "画面与文字搭配自然，翻阅体验完整流畅"],
    ["角色设定很有童趣，法宝与危机转折富有想象力", "构图景别有变化，大场面与细节兼顾得不错", "整体绘本装帧整洁，是一本让人想反复翻看的佳作"],
    ["小故事充满真诚的情感与机智破局的巧思", "画风统一柔和，能感受到大主编逐页审片的用心", "图文相互补充，文字简洁又有画面感"],
]

FALLBACK_SUGGESTIONS = [
    "下次可以尝试给最关键的一幕加上大远景或特写对比，让冒险更震撼！",
    "继续保持角色形象一致性的好习惯，试试设计一个意想不到的小彩蛋结局吧！",
    "很棒的一本小书！下一次可以挑战给配角也加上专属动作和表情细节。",
]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
HTML_EXTENSIONS = {".html", ".htm"}
TEXT_EXTENSIONS = {".txt", ".md"}
IGNORED_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini"}
GENERIC_AUTHORS = {"", "小作者", "神秘小作者", "未知作者"}
GENERIC_TITLES = {"", "我的绘本", "未命名绘本"}

MUSIC_PATH = Path(__file__).resolve().parent.parent / "assets" / "award-music.mp3"


def natural_sort_key(text: str) -> list[Any]:
    """Sort strings naturally so p2 comes before p10."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def escape_html(text: Any) -> str:
    """Escape HTML special characters for safe template insertion."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def json_for_script(data: Any) -> str:
    """Serialize JSON safely for inline <script> blocks (prevents </script> XSS)."""
    raw = json.dumps(data, ensure_ascii=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def safe_csv_cell(value: Any) -> Any:
    """Neutralize spreadsheet formula prefixes (=, +, -, @, tab, CR, LF) including leading whitespace."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip(" \t\r\n")
    if (value and value[0] in ("=", "+", "-", "@", "\t", "\r", "\n")) or (
        stripped and stripped[0] in ("=", "+", "-", "@")
    ):
        return "'" + value
    return value


def parse_author_project(stem: str) -> tuple[str | None, str]:
    """Split '姓名-作品名' into (author, project); ignore pure numeric ordering prefixes."""
    clean = stem.strip()
    for sep in ("-", "—", "－"):
        if sep in clean:
            author, _, project = clean.partition(sep)
            a = author.strip()
            p = project.strip()
            if a and p:
                if re.fullmatch(r"\d+", a):
                    return parse_author_project(p)
                return a, p
    return None, clean


def decode_data_uri(uri: str) -> bytes | None:
    """Decode a data:image/...;base64,... URI into raw bytes."""
    if not uri or not isinstance(uri, str) or not uri.startswith("data:"):
        return None
    header, sep, payload = uri.partition(",")
    if not sep or ";base64" not in header.lower():
        return None
    try:
        return base64.b64decode(payload)
    except Exception:
        return None


def load_pil_image(source: bytes | Path | str) -> Image.Image | None:
    """Load an image from bytes, a file Path, or a data URI."""
    try:
        if isinstance(source, bytes):
            img = Image.open(io.BytesIO(source))
            img.load()
            return img
        if isinstance(source, Path):
            img = Image.open(source)
            img.load()
            return img
        if isinstance(source, str):
            if source.startswith("data:"):
                raw = decode_data_uri(source)
                if raw is None:
                    return None
                img = Image.open(io.BytesIO(raw))
                img.load()
                return img
            p = Path(source)
            if p.is_file():
                img = Image.open(p)
                img.load()
                return img
    except Exception:
        return None
    return None


def image_to_jpeg_bytes(img: Image.Image, max_width: int, quality: int = 78) -> bytes:
    """Convert PIL image to RGB, optionally downscale, and encode as JPEG bytes."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        rgb = bg
    else:
        rgb = img.convert("RGB")
    w, h = rgb.size
    if max_width > 0 and w > max_width:
        ratio = max_width / w
        rgb = rgb.resize((max_width, max(1, int(h * ratio))), Image.LANCZOS)
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def image_to_data_uri(source: bytes | Path | str, max_width: int = 560, quality: int = 76) -> str | None:
    """Load image, compress to JPEG, and return data URI."""
    img = load_pil_image(source)
    if img is None:
        return None
    try:
        jpeg = image_to_jpeg_bytes(img, max_width=max_width, quality=quality)
        return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
    except Exception:
        return None


def _load_cjk_or_default_font(size: int = 16) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Locate a readable font for contact-sheet tile labels."""
    candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for fp in candidates:
        if fp.is_file():
            try:
                return ImageFont.truetype(str(fp), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def remove_white_background(img: Image.Image) -> Image.Image:
    """Make near-white pixels transparent while preserving saturated colors."""
    rgba = img.convert("RGBA")
    threshold = 12000
    pixel_iter = rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata()
    pixels = [
        (255, 255, 255, 0)
        if ((255 - r) ** 2 + (255 - g) ** 2 + (255 - b) ** 2) < threshold
        else (r, g, b, a)
        for (r, g, b, a) in pixel_iter
    ]
    out = Image.new("RGBA", rgba.size)
    out.putdata(pixels)
    return out


def parse_logo_spec(spec: str) -> tuple[Path, str]:
    """Parse --logo value 'path' or 'path|alt_text' safely on Windows and POSIX."""
    if "|" in spec:
        raw_path, _, alt = spec.partition("|")
        p = Path(raw_path.strip()).expanduser()
        return p, alt.strip() or p.stem
    p = Path(spec.strip()).expanduser()
    return p, p.stem


def load_logo_data(path: Path, max_height: int = 120) -> str | None:
    """Load an optional logo image, resize, and return a PNG data URI."""
    if not path.is_file():
        print(f"Warning: logo file not found, skipping: {path}", file=sys.stderr)
        return None
    try:
        img = Image.open(path)
        had_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        rgba = img.convert("RGBA")
        w, h = rgba.size
        if h > max_height:
            ratio = max_height / h
            rgba = rgba.resize((max(1, int(w * ratio)), max_height), Image.LANCZOS)
        if not had_alpha:
            rgba = remove_white_background(rgba)
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        print(f"Warning: could not load logo {path}: {exc}", file=sys.stderr)
        return None


def build_site_logos_html(logo_specs: list[str]) -> str:
    """Build optional top-left logo strip from CLI --logo arguments."""
    imgs: list[str] = []
    for spec in logo_specs:
        path, alt = parse_logo_spec(spec)
        uri = load_logo_data(path)
        if uri:
            imgs.append(f'<img src="{uri}" alt="{escape_html(alt)}" class="site-logo">')
    if not imgs:
        return ""
    return '<div class="site-logos">' + "".join(imgs) + "</div>"


def load_music_data(music_arg: str | None, no_music: bool) -> str | None:
    """Load background music MP3 as base64 data URI unless disabled or missing."""
    if no_music:
        return None
    target = Path(music_arg).expanduser() if music_arg else MUSIC_PATH
    if not target.is_file():
        if music_arg:
            print(f"Warning: music file not found, skipping: {target}", file=sys.stderr)
        return None
    try:
        b64 = base64.b64encode(target.read_bytes()).decode("ascii")
        return f"data:audio/mpeg;base64,{b64}"
    except Exception as exc:
        print(f"Warning: could not load music {target}: {exc}", file=sys.stderr)
        return None


def _decode_zip_filename(member: zipfile.ZipInfo) -> str:
    """Decode ZipInfo filename, recovering GBK/UTF-8 names when bit 0x800 is unset."""
    name = member.filename
    if not (member.flag_bits & 0x800):
        try:
            raw = name.encode("cp437")
        except UnicodeEncodeError:
            raw = None
        if raw is not None:
            for enc in ("gb18030", "utf-8"):
                try:
                    name = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
    return name


def _validate_zip_relpath(raw_name: str) -> tuple[Path, bool]:
    """Validate and normalize a decoded zip path against Zip-Slip and absolute escapes."""
    if "\x00" in raw_name:
        raise ValueError(f"Unsafe zip entry path blocked: {raw_name!r}")
    is_dir = raw_name.endswith(("/", "\\"))
    normalized = raw_name.replace("\\", "/")
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or PureWindowsPath(raw_name).drive
        or PureWindowsPath(raw_name).is_absolute()
        or PurePosixPath(normalized).is_absolute()
    ):
        raise ValueError(f"Unsafe zip entry path blocked: {raw_name}")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"Unsafe zip entry path blocked: {raw_name}")
    if not parts:
        return Path("."), True
    return Path(*parts), is_dir


def extract_zip_safe(zip_path: Path) -> Path:
    """Extract a .zip archive into a temp directory with GBK decoding and Zip-Slip protection."""
    temp_dir = Path(tempfile.mkdtemp(prefix="picture-book-judge-"))
    resolved_root = temp_dir.resolve()
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                decoded_name = _decode_zip_filename(member)
                rel_path, is_dir_flag = _validate_zip_relpath(decoded_name)
                mode = (member.external_attr >> 16) & 0xFFFF
                if mode and stat.S_ISLNK(mode):
                    raise ValueError(f"Unsafe symlink zip entry blocked: {decoded_name}")
                target = (resolved_root / rel_path).resolve()
                if target != resolved_root and resolved_root not in target.parents:
                    raise ValueError(f"Unsafe zip entry path blocked: {decoded_name}")
                if member.is_dir() or is_dir_flag:
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member, "r") as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return temp_dir


def parse_stpageflip_html(html_text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Extract TITLE, AUTHOR, DATE, COVER, and PAGES from a StPageFlip book HTML.

    Scans the whole HTML document without fixed-byte truncation so the ~44KB
    embedded page-flip.browser.js library never hides the story data.
    """
    warnings: list[str] = []
    # Locate the declaration block starting at TITLE = ... (skipping embedded library scripts)
    m_start = re.search(r"(?:const|var|let)\s+TITLE\s*=", html_text)
    if not m_start:
        return None, warnings

    decoder = json.JSONDecoder()
    data: dict[str, Any] = {}
    pos = m_start.start()
    target_vars = ("TITLE", "AUTHOR", "DATE", "COVER", "PAGES")
    var_pattern = re.compile(
        r"(?:^|[;,\s])(?:(?:const|var|let)\s+)?(TITLE|AUTHOR|DATE|COVER|PAGES)\s*="
    )

    while pos < len(html_text) and len(data) < len(target_vars):
        m = var_pattern.search(html_text, pos)
        if not m:
            break
        var_name = m.group(1)
        val_start = m.end()
        while val_start < len(html_text) and html_text[val_start].isspace():
            val_start += 1
        if val_start >= len(html_text):
            break
        try:
            val, end_offset = decoder.raw_decode(html_text, val_start)
            data[var_name] = val
            pos = end_offset
        except json.JSONDecodeError:
            # Advance past '=' to avoid infinite loop on non-JSON expression
            pos = val_start + 1

    if "PAGES" not in data and "COVER" not in data:
        warnings.append("检测到 TITLE 声明但未能解析出有效的 PAGES/COVER 数据")
        return None, warnings

    raw_pages = data.get("PAGES")
    if not isinstance(raw_pages, list):
        raw_pages = []
        warnings.append("HTML 中的 PAGES 字段不是有效数组")

    pages: list[dict[str, Any]] = []
    for idx, pg in enumerate(raw_pages):
        if isinstance(pg, dict):
            pages.append({
                "page": idx + 1,
                "text": str(pg.get("text") or "").strip(),
                "img": str(pg.get("img") or ""),
            })
        elif isinstance(pg, str):
            pages.append({"page": idx + 1, "text": pg.strip(), "img": ""})

    return {
        "title": str(data.get("TITLE") or "").strip(),
        "author": str(data.get("AUTHOR") or "").strip(),
        "date": str(data.get("DATE") or "").strip(),
        "cover": str(data.get("COVER") or ""),
        "pages": pages,
    }, warnings


def parse_generic_html(html_text: str, base_dir: Path | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Fallback parser for non-StPageFlip HTML picture books."""
    warnings: list[str] = []
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    title = html_lib.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip() if title_match else ""

    imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_text, re.IGNORECASE)
    # Strip <script> and <style> before extracting readable text snippets
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    text_blocks = [
        html_lib.unescape(re.sub(r"<[^>]+>", "", m)).strip()
        for m in re.findall(r"<(?:p|h[1-6]|figcaption|div[^>]*class=[\"'][^\"']*cap[^\"']*[\"'])[^>]*>(.*?)</(?:p|h[1-6]|figcaption|div)>", cleaned, re.IGNORECASE | re.DOTALL)
    ]
    text_blocks = [t for t in text_blocks if t]

    resolved_imgs: list[str] = []
    for src in imgs:
        if src.startswith("data:image/"):
            resolved_imgs.append(src)
        elif base_dir is not None:
            candidate = (base_dir / src).resolve()
            if base_dir.resolve() in candidate.parents or candidate.parent == base_dir.resolve():
                if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
                    resolved_imgs.append(str(candidate))

    if not resolved_imgs and not text_blocks:
        return None, ["HTML 文件中未发现可识别的绘本页面数据、图片或故事文本"]

    warnings.append("非标准 StPageFlip 格式 HTML，已按通用图文结构降级解析")
    cover = resolved_imgs[0] if resolved_imgs else ""
    inner_imgs = resolved_imgs[1:] if len(resolved_imgs) > 1 else resolved_imgs
    count = max(len(inner_imgs), len(text_blocks))
    pages = []
    for i in range(count):
        pages.append({
            "page": i + 1,
            "text": text_blocks[i] if i < len(text_blocks) else "",
            "img": inner_imgs[i] if i < len(inner_imgs) else "",
        })
    return {
        "title": title,
        "author": "",
        "date": "",
        "cover": cover,
        "pages": pages,
    }, warnings


def parse_html_book_file(html_path: Path) -> tuple[dict[str, Any] | None, str, list[str]]:
    """Read and parse a picture-book HTML file without truncation."""
    try:
        text = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, "unreadable", [f"无法读取 HTML 文件 {html_path.name}: {exc}"]

    parsed, warnings = parse_stpageflip_html(text)
    if parsed is not None:
        return parsed, "stpageflip_html", warnings

    generic, gen_warnings = parse_generic_html(text, base_dir=html_path.parent)
    if generic is not None:
        return generic, "generic_html", warnings + gen_warnings
    return None, "unparseable", warnings + gen_warnings


def _find_image_for_name(search_dirs: list[Path], name_stem: str) -> Path | None:
    """Find an image file matching a given stem across candidate directories."""
    if not name_stem:
        return None
    for d in search_dirs:
        if not d.is_dir():
            continue
        for ext in IMAGE_EXTENSIONS:
            cand = d / f"{name_stem}{ext}"
            if cand.is_file():
                return cand
        # Also match prefixed names like 01_p01.png or 02_p1.png
        for entry in sorted(d.iterdir(), key=lambda p: natural_sort_key(p.name)):
            if entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSIONS:
                if entry.stem.lower() == name_stem.lower() or entry.stem.lower().endswith("_" + name_stem.lower()):
                    return entry
    return None


def parse_story_json_dir(project_dir: Path, story_path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse story.json + associated image files in a project folder."""
    warnings: list[str] = []
    try:
        story = json.loads(story_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [f"story.json 解析失败 ({exc})"]

    if not isinstance(story, dict):
        return None, ["story.json 根节点不是 JSON 对象"]

    search_dirs = [project_dir, project_dir / "out", project_dir / "images", project_dir / "imgs"]
    cover_path = _find_image_for_name(search_dirs, "cover") or _find_image_for_name(search_dirs, "01_cover")

    all_images: list[Path] = []
    for d in search_dirs:
        if d.is_dir():
            all_images.extend(
                sorted(
                    (e for e in d.iterdir() if e.is_file() and e.suffix.lower() in IMAGE_EXTENSIONS),
                    key=lambda e: natural_sort_key(e.name),
                )
            )
    if cover_path is None:
        for img_p in all_images:
            if "cover" in img_p.stem.lower() or "封面" in img_p.stem:
                cover_path = img_p
                break

    raw_pages = story.get("pages") if isinstance(story.get("pages"), list) else []
    pages: list[dict[str, Any]] = []
    non_cover_imgs = [
        p for p in all_images
        if p != cover_path and "anchor" not in p.stem.lower() and not p.stem.lower().startswith("comp_")
    ]

    for idx, pg in enumerate(raw_pages):
        if not isinstance(pg, dict):
            continue
        name = str(pg.get("name") or f"p{idx+1:02d}")
        text = str(pg.get("caption") or pg.get("text") or "").strip()
        img_ref = pg.get("img")
        img_path: Path | None = None
        if isinstance(img_ref, str) and img_ref.strip():
            cand = (project_dir / img_ref).resolve()
            if cand.is_file():
                img_path = cand
        if img_path is None:
            img_path = _find_image_for_name(search_dirs, name)
        if img_path is None and idx < len(non_cover_imgs):
            img_path = non_cover_imgs[idx]
        pages.append({
            "page": idx + 1,
            "text": text,
            "img": str(img_path) if img_path else "",
        })

    if not pages and not cover_path:
        warnings.append("story.json 中未包含可用页面或图片")

    return {
        "title": str(story.get("title") or "").strip(),
        "author": str(story.get("author") or "").strip(),
        "date": str(story.get("date") or "").strip(),
        "cover": str(cover_path) if cover_path else "",
        "pages": pages,
    }, warnings


def parse_image_folder(project_dir: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Parse a folder containing loose images (and optional text captions)."""
    warnings: list[str] = []
    imgs = sorted(
        (
            e for e in project_dir.rglob("*")
            if e.is_file() and e.suffix.lower() in IMAGE_EXTENSIONS
            and "anchor" not in e.stem.lower() and not e.stem.lower().startswith("comp_")
        ),
        key=lambda e: natural_sort_key(str(e.relative_to(project_dir))),
    )
    if not imgs:
        return None, ["目录中未找到任何绘本 HTML、story.json 或图片文件"]

    cover_path: Path | None = None
    inner_imgs: list[Path] = []
    for p in imgs:
        stem_low = p.stem.lower()
        if cover_path is None and ("cover" in stem_low or "封面" in p.stem or stem_low.startswith("00_")):
            cover_path = p
        else:
            inner_imgs.append(p)

    if cover_path is None:
        cover_path = imgs[0]
        inner_imgs = imgs[1:] if len(imgs) > 1 else imgs

    # Look for optional caption lines in a single .txt/.md file
    captions: list[str] = []
    for txt_file in sorted(project_dir.iterdir(), key=lambda e: e.name):
        if txt_file.is_file() and txt_file.suffix.lower() in TEXT_EXTENSIONS:
            try:
                lines = [ln.strip() for ln in txt_file.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
                if lines:
                    captions = lines
                    break
            except OSError:
                pass

    pages = []
    for idx, img_p in enumerate(inner_imgs):
        pages.append({
            "page": idx + 1,
            "text": captions[idx] if idx < len(captions) else "",
            "img": str(img_p),
        })
    if not captions:
        warnings.append("散装图片目录未附带文字脚本，已提取全部画面供视觉评审")

    return {
        "title": "",
        "author": "",
        "date": "",
        "cover": str(cover_path),
        "pages": pages,
    }, warnings


def resolve_author_and_title(
    file_stem: str,
    meta_author: str,
    meta_title: str,
) -> tuple[str, str]:
    """Combine filename '姓名-作品名' with internal metadata cleanly."""
    file_author, file_title = parse_author_project(file_stem)

    if file_author:
        author = file_author
    elif meta_author and meta_author not in GENERIC_AUTHORS:
        author = meta_author
    else:
        author = "神秘小作者"

    if meta_title and meta_title not in GENERIC_TITLES:
        project = meta_title
    elif file_title:
        project = file_title
    else:
        project = file_stem

    return author, project


ASSET_DIR_NAMES = {"images", "image", "imgs", "pages", "assets", "static", "pic", "pics"}


def find_project_root(input_path: Path) -> Path:
    """Unwrap single batch-wrapper directories (even with '-' in name) without unwrapping book folders."""
    current = input_path
    for _ in range(3):
        entries = [e for e in current.iterdir() if e.name not in IGNORED_NAMES and not e.name.startswith(".")]
        dirs = [e for e in entries if e.is_dir()]
        files = [e for e in entries if e.is_file()]
        if len(dirs) != 1 or files:
            break
        sole = dirs[0]
        sole_children = [c for c in sole.iterdir() if c.name not in IGNORED_NAMES and not c.name.startswith(".")]
        if (sole / "story.json").is_file():
            break
        if any(c.is_file() and c.suffix.lower() in IMAGE_EXTENSIONS for c in sole_children):
            break
        sub_dirs = [c for c in sole_children if c.is_dir()]
        html_files = [c for c in sole_children if c.is_file() and c.suffix.lower() in HTML_EXTENSIONS]
        non_asset_dirs = [d for d in sub_dirs if d.name.lower() not in ASSET_DIR_NAMES]
        if len(html_files) >= 2 or len(non_asset_dirs) >= 1 or (len(html_files) == 1 and not sub_dirs):
            current = sole
            continue
        break
    return current


def discover_books(input_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Discover all picture-book submissions from a directory without silent skipping."""
    root = find_project_root(input_path)
    books: list[dict[str, Any]] = []
    global_warnings: list[str] = []

    entries = sorted(
        (e for e in root.iterdir() if e.name not in IGNORED_NAMES and not e.name.startswith(".")),
        key=lambda e: natural_sort_key(e.name),
    )

    seen_identities: dict[tuple[str, str], str] = {}
    book_seq = 0

    for entry in entries:
        parsed: dict[str, Any] | None = None
        source_type = ""
        warnings: list[str] = []
        source_file = entry.name

        if entry.is_file():
            if entry.suffix.lower() in HTML_EXTENSIONS:
                parsed, source_type, warnings = parse_html_book_file(entry)
                if parsed is None:
                    msg = f"跳过无法解析的顶层 HTML 文件 {entry.name}: {'; '.join(warnings)}"
                    print(f"Warning: {msg}", file=sys.stderr)
                    global_warnings.append(msg)
                    continue
            else:
                msg = f"跳过不支持的顶层文件 {entry.name}（仅支持 .html/.htm 或作品子目录）"
                print(f"Warning: {msg}", file=sys.stderr)
                global_warnings.append(msg)
                continue
        elif entry.is_dir():
            html_files = sorted(
                (f for f in entry.iterdir() if f.is_file() and f.suffix.lower() in HTML_EXTENSIONS),
                key=lambda f: natural_sort_key(f.name),
            )
            story_json = entry / "story.json"
            if html_files:
                if len(html_files) > 1:
                    warnings.append(f"目录内包含多个 HTML 文件，优先读取 {html_files[0].name}")
                for hf in html_files:
                    cand, stype, w = parse_html_book_file(hf)
                    if cand is not None:
                        parsed = cand
                        source_type = stype
                        warnings.extend(w)
                        source_file = f"{entry.name}/{hf.name}"
                        break
                    warnings.extend(w)
            if parsed is None and story_json.is_file():
                parsed, w = parse_story_json_dir(entry, story_json)
                source_type = "story_json"
                warnings.extend(w)
                source_file = f"{entry.name}/story.json"
            if parsed is None:
                parsed, w = parse_image_folder(entry)
                if parsed is not None:
                    source_type = "image_folder"
                    warnings.extend(w)
                else:
                    msg = f"跳过空目录或无效作品目录 {entry.name}: {'; '.join(warnings + w)}"
                    print(f"Warning: {msg}", file=sys.stderr)
                    global_warnings.append(msg)
                    continue
        else:
            continue

        book_seq += 1
        book_id = f"book-{book_seq:03d}"
        stem = entry.stem if entry.is_file() else entry.name
        author, project = resolve_author_and_title(stem, parsed.get("author", ""), parsed.get("title", ""))

        identity = (author.lower(), project.lower())
        if identity in seen_identities:
            dup_msg = (
                f"{book_id} ({author} - 《{project}》) 与 {seen_identities[identity]} 同名，疑似重复提交"
                "（请按活动规则核对是否保留第 1 份）"
            )
            warnings.append(dup_msg)
            global_warnings.append(dup_msg)
        else:
            seen_identities[identity] = book_id

        pages = parsed.get("pages") or []
        if not pages:
            warnings.append("内页列表为空（0 页内页）")
        empty_img_pages = [p["page"] for p in pages if not p.get("img")]
        if empty_img_pages:
            warnings.append(f"第 {empty_img_pages} 页缺少图片")

        books.append({
            "id": book_id,
            "key": stem,
            "author": author,
            "project": project,
            "date": parsed.get("date") or "",
            "source_type": source_type,
            "source_file": source_file,
            "path": str(entry),
            "cover": parsed.get("cover") or "",
            "pages": pages,
            "warnings": warnings,
        })

    return books, global_warnings


def build_contact_sheets(
    book: dict[str, Any],
    review_dir: Path,
    tiles_per_sheet: int = 16,
) -> tuple[str | None, list[str]]:
    """Generate lightweight cover preview + grid contact sheet(s) in review-assets/."""
    book_id = book["id"]
    cover_rel: str | None = None
    sheet_rels: list[str] = []

    cover_src = book.get("cover") or ""
    if not cover_src:
        for pg in book.get("pages") or []:
            if pg.get("img"):
                cover_src = pg["img"]
                break

    if cover_src:
        cover_img = load_pil_image(cover_src)
        if cover_img is not None:
            cover_file = review_dir / f"{book_id}-cover.jpg"
            cover_file.write_bytes(image_to_jpeg_bytes(cover_img, max_width=480, quality=78))
            cover_rel = f"review-assets/{cover_file.name}"

    tiles: list[tuple[str, Any, str]] = []
    if book.get("cover"):
        tiles.append(("COVER", book["cover"], f"《{book['project']}》"))
    for pg in book.get("pages") or []:
        if pg.get("img"):
            tiles.append((f"P{pg['page']:02d}", pg["img"], pg.get("text", "")))

    if not tiles:
        return cover_rel, sheet_rels

    font = _load_cjk_or_default_font(15)
    cols = 4
    tile_w = 300
    tile_img_h = 380
    header_h = 28
    pad = 12
    cell_h = header_h + tile_img_h

    chunks = [tiles[i:i + tiles_per_sheet] for i in range(0, len(tiles), tiles_per_sheet)]
    for chunk_idx, chunk in enumerate(chunks):
        rows = (len(chunk) + cols - 1) // cols
        canvas_w = pad + cols * (tile_w + pad)
        canvas_h = pad + rows * (cell_h + pad)
        canvas = Image.new("RGB", (canvas_w, canvas_h), (244, 239, 230))
        draw = ImageDraw.Draw(canvas)

        for idx, (label, img_src, _caption) in enumerate(chunk):
            r, c = divmod(idx, cols)
            x0 = pad + c * (tile_w + pad)
            y0 = pad + r * (cell_h + pad)

            # Tile frame & dark header strip with crisp ASCII page badge
            draw.rectangle([x0, y0, x0 + tile_w, y0 + cell_h], fill=(255, 255, 255), outline=(210, 200, 184))
            draw.rectangle([x0, y0, x0 + tile_w, y0 + header_h], fill=(58, 51, 90))
            draw.text((x0 + 8, y0 + 5), label, fill=(255, 214, 107), font=font)

            tile_img = load_pil_image(img_src)
            if tile_img is not None:
                if tile_img.mode != "RGB":
                    tile_img = tile_img.convert("RGB")
                iw, ih = tile_img.size
                scale = min(tile_w / iw, tile_img_h / ih)
                nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
                resized = tile_img.resize((nw, nh), Image.LANCZOS)
                ox = x0 + (tile_w - nw) // 2
                oy = y0 + header_h + (tile_img_h - nh) // 2
                canvas.paste(resized, (ox, oy))

        suffix = "" if len(chunks) == 1 else f"-{chunk_idx + 1}"
        sheet_file = review_dir / f"{book_id}-sheet{suffix}.jpg"
        sheet_file.write_bytes(image_to_jpeg_bytes(canvas, max_width=0, quality=76))
        sheet_rels.append(f"review-assets/{sheet_file.name}")

    return cover_rel, sheet_rels


def prepare_review_assets(
    books: list[dict[str, Any]],
    output_dir: Path,
    global_warnings: list[str],
    event_label: str,
    award_titles: list[str],
) -> Path:
    """Create review-assets/ thumbnails + contact sheets and write compact manifest.json."""
    review_dir = output_dir / "review-assets"
    review_dir.mkdir(parents=True, exist_ok=True)
    # Remove stale review assets from earlier runs so deleted submissions don't linger
    for old in review_dir.glob("*.jpg"):
        old.unlink(missing_ok=True)

    manifest_books: list[dict[str, Any]] = []
    for book in books:
        cover_rel, sheet_rels = build_contact_sheets(book, review_dir)
        book["cover_preview"] = cover_rel
        book["contact_sheets"] = sheet_rels
        manifest_books.append({
            "id": book["id"],
            "key": book["key"],
            "author": book["author"],
            "project": book["project"],
            "date": book["date"],
            "source_type": book["source_type"],
            "source_file": book["source_file"],
            "page_count": len(book["pages"]),
            "has_cover": bool(book.get("cover")),
            "cover_preview": cover_rel,
            "contact_sheets": sheet_rels,
            "warnings": book["warnings"],
            "pages": [
                {"page": p["page"], "text": p["text"], "has_image": bool(p.get("img"))}
                for p in book["pages"]
            ],
        })

    manifest_path = output_dir / "manifest.json"
    manifest = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "event": event_label,
        "awards": award_titles,
        "total_books": len(manifest_books),
        "warnings": global_warnings,
        "books": manifest_books,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def print_discovery_summary(
    books: list[dict[str, Any]],
    output_dir: Path,
    manifest_path: Path,
    global_warnings: list[str],
    award_titles: list[str],
) -> None:
    """Print a concise context-safe discovery report and scores.json schema example."""
    print("=== DISCOVERED PICTURE BOOKS ===")
    summary = [
        {
            "id": b["id"],
            "author": b["author"],
            "project": b["project"],
            "pages": len(b["pages"]),
            "source_type": b["source_type"],
            "source_file": b["source_file"],
            "cover_preview": b.get("cover_preview"),
            "contact_sheets": b.get("contact_sheets"),
            "warnings": b["warnings"],
        }
        for b in books
    ]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if global_warnings:
        print("\n=== WARNINGS ===")
        for w in global_warnings:
            print(f"  - {w}")

    print("\n=== NEXT STEPS ===")
    print(f"1. Read structured text & captions from: {manifest_path}")
    print(f"2. Visually inspect contact sheets in batches (4-5 books/batch) under: {output_dir / 'review-assets'}")
    print(f"3. Write final evaluations to: {output_dir / 'scores.json'}")
    print("\nExample scores.json:")
    example_participants = [
        {
            "id": b["id"],
            "author": b["author"],
            "project": b["project"],
            "scores": {d: 19 for d in DIMENSIONS},
            "strengths": [
                "四幕故事完整有趣，危机与破局设计巧妙",
                "主角造型跨页稳定，画面色彩与景别很有层次",
                "图文配合自然贴切，画面文字清晰准确",
            ],
            "suggestion": "下次可以挑战在结局页加一个小彩蛋，让故事更让人回味！",
        }
        for b in books[:2]
    ]
    print(json.dumps({
        "version": 1,
        "participants": example_participants,
        "awards": [
            {"id": DEFAULT_AWARDS[i]["id"], "title": award_titles[i]}
            for i in range(3)
        ],
    }, ensure_ascii=False, indent=2))


def load_scores(output_dir: Path) -> dict[str, Any] | None:
    scores_path = output_dir / "scores.json"
    if not scores_path.exists():
        return None
    with open(scores_path, "r", encoding="utf-8") as f:
        return json.load(f)


def clamp_score(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    return int(max(0, min(20, round(numeric))))


def award_priority(award: dict[str, Any]) -> list[str]:
    """Return dimension priority order tailored to a picture-book award title."""
    title = award.get("title", "")
    if "故事" in title:
        return ["故事结构与完整性", "创意想象力", "图文契合度", "完成度与细节", "画面表现与角色一致性"]
    if "画面" in title or "美术" in title or "视觉" in title:
        return ["画面表现与角色一致性", "图文契合度", "完成度与细节", "创意想象力", "故事结构与完整性"]
    if "创意" in title or "想象" in title or "脑洞" in title:
        return ["创意想象力", "故事结构与完整性", "画面表现与角色一致性", "图文契合度", "完成度与细节"]
    return DIMENSIONS.copy()


def award_fit_key(participant: dict[str, Any], award: dict[str, Any]) -> tuple[float, ...]:
    scores = participant["scores"]
    total = sum(scores.get(d, 0) for d in DIMENSIONS)
    return (total, *(scores.get(d, 0) for d in award_priority(award)))


def select_best_for_award(candidates: list[dict[str, Any]], award: dict[str, Any]) -> dict[str, Any]:
    return max(candidates, key=lambda p: (*award_fit_key(p, award), p["id"]))


def select_award_for_participant(participant: dict[str, Any], awards: list[dict[str, Any]]) -> int:
    return max(
        range(len(awards)),
        key=lambda idx: (
            award_fit_key(participant, awards[idx]),
            -len(awards[idx]["winnerIds"]),
            -idx,
        ),
    )


def resolve_winner_ids(
    raw_winner_ids: Any,
    key_to_id: dict[str, str],
    id_to_participant: dict[str, dict[str, Any]],
) -> list[str]:
    if raw_winner_ids is None:
        return []
    values = [raw_winner_ids] if isinstance(raw_winner_ids, str) else list(raw_winner_ids) if isinstance(raw_winner_ids, list) else []
    resolved: list[str] = []
    seen: set[str] = set()
    for item in values:
        ref = str(item).strip()
        if not ref:
            continue
        pid = ref if ref in id_to_participant else key_to_id.get(ref)
        if pid is None:
            print(f"Warning: ignoring unknown winner reference {ref!r}", file=sys.stderr)
            continue
        if pid not in seen:
            resolved.append(pid)
            seen.add(pid)
    return resolved


def normalize_scores(
    scores: dict[str, Any],
    books: list[dict[str, Any]],
    award_titles: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge scores.json entries with discovered books and distribute across 3 awards."""
    raw_participants = scores.get("participants")
    entries_by_id: dict[str, dict[str, Any]] = {}
    entries_by_key: dict[str, dict[str, Any]] = {}

    if isinstance(raw_participants, list):
        for entry in raw_participants:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or "").strip()
            ekey = str(entry.get("key") or "").strip()
            if eid:
                entries_by_id[eid] = entry
            if ekey:
                entries_by_key[ekey] = entry
    elif isinstance(scores, dict):
        # Legacy dict keyed by "作者-作品" or id
        for k, v in scores.items():
            if isinstance(v, dict) and "scores" in v:
                entries_by_key[str(k)] = v

    participants: list[dict[str, Any]] = []
    for idx, book in enumerate(books):
        pid = book["id"]
        key = book["key"]
        entry = entries_by_id.get(pid) or entries_by_key.get(key) or entries_by_key.get(f"{book['author']}-{book['project']}") or {}
        raw_scores = entry.get("scores") if isinstance(entry.get("scores"), dict) else {}

        merged_scores = {d: clamp_score(raw_scores.get(d, 0)) for d in DIMENSIONS}
        if not raw_scores:
            print(f"Warning: missing scores for {pid} ({book['author']} - {book['project']}), defaulting to 0", file=sys.stderr)

        strengths = entry.get("strengths")
        if not isinstance(strengths, list) or not [str(s).strip() for s in strengths if str(s).strip()]:
            strengths = FALLBACK_STRENGTHS[idx % len(FALLBACK_STRENGTHS)]
        else:
            strengths = [str(s).strip() for s in strengths if str(s).strip()][:3]

        suggestion = str(entry.get("suggestion") or "").strip() or FALLBACK_SUGGESTIONS[idx % len(FALLBACK_SUGGESTIONS)]
        author = str(entry.get("author") or "").strip() or book["author"]
        project = str(entry.get("project") or "").strip() or book["project"]

        participants.append({
            "id": pid,
            "key": key,
            "author": author,
            "project": project,
            "page_count": len(book["pages"]),
            "source_file": book["source_file"],
            "scores": merged_scores,
            "strengths": strengths,
            "suggestion": suggestion,
            "comment": str(entry.get("comment") or "").strip(),
        })

    key_to_id = {p["key"]: p["id"] for p in participants}
    id_to_participant = {p["id"]: p for p in participants}

    raw_awards = scores.get("awards") if isinstance(scores.get("awards"), list) else []
    normalized_awards: list[dict[str, Any]] = []
    for i, title in enumerate(award_titles):
        base = DEFAULT_AWARDS[i % len(DEFAULT_AWARDS)].copy()
        user_award = raw_awards[i] if i < len(raw_awards) and isinstance(raw_awards[i], dict) else {}
        base.update({k: v for k, v in user_award.items() if v is not None})
        # Explicit --awards override takes precedence if user didn't rename inside awards list
        if "title" not in user_award or award_titles != DEFAULT_AWARD_TITLES:
            base["title"] = title
        base.setdefault("id", f"award-{i+1:03d}")
        base.setdefault("icon", DEFAULT_AWARDS[i % len(DEFAULT_AWARDS)]["icon"])
        base.setdefault("theme", DEFAULT_AWARDS[i % len(DEFAULT_AWARDS)]["theme"])

        raw_wids = base.pop("winnerIds", None)
        if raw_wids is None:
            raw_wids = base.pop("winner_ids", None)
        if raw_wids is None:
            raw_wids = base.pop("winnerId", None)
        if raw_wids is None:
            raw_wids = base.pop("winner_id", None)
        base["winnerIds"] = resolve_winner_ids(raw_wids, key_to_id, id_to_participant)
        normalized_awards.append(base)

    # Deduplicate manually assigned winners across awards
    claimed_ids: set[str] = set()
    for award in normalized_awards:
        unique_wids: list[str] = []
        for wid in award["winnerIds"]:
            if wid not in claimed_ids:
                unique_wids.append(wid)
                claimed_ids.add(wid)
        award["winnerIds"] = unique_wids

    # Default even snake-draft distribution when no manual winners are specified
    if not any(award["winnerIds"] for award in normalized_awards):
        ranked = sorted(
            participants,
            key=lambda p: (sum(p["scores"].get(d, 0) for d in DIMENSIONS), p["id"]),
            reverse=True,
        )
        num_awards = len(normalized_awards)
        for rank_idx, participant in enumerate(ranked):
            round_idx, pos_in_round = divmod(rank_idx, num_awards)
            award_pos = pos_in_round if round_idx % 2 == 0 else num_awards - 1 - pos_in_round
            normalized_awards[award_pos]["winnerIds"].append(participant["id"])
        return participants, normalized_awards

    # Fill any empty awards first, then place remaining unassigned participants
    assigned_ids = {wid for a in normalized_awards for wid in a["winnerIds"]}
    for award in normalized_awards:
        if award["winnerIds"]:
            continue
        candidates = [p for p in participants if p["id"] not in assigned_ids]
        if not candidates:
            break
        best = select_best_for_award(candidates, award)
        award["winnerIds"].append(best["id"])
        assigned_ids.add(best["id"])

    for participant in participants:
        if participant["id"] in assigned_ids or not normalized_awards:
            continue
        award_idx = select_award_for_participant(participant, normalized_awards)
        normalized_awards[award_idx]["winnerIds"].append(participant["id"])
        assigned_ids.add(participant["id"])

    return participants, normalized_awards


def compute_total(scores: dict[str, int | float]) -> int:
    return int(sum(scores.get(d, 0) for d in DIMENSIONS))


def qualitative_label(avg_score: float) -> str:
    if avg_score >= 19.0:
        return "妙笔生花"
    if avg_score >= 18.0:
        return "表现出色"
    if avg_score >= 17.0:
        return "创意满满"
    return "潜力无限"


def select_preview_pages(book: dict[str, Any], max_previews: int = 4) -> list[dict[str, Any]]:
    """Select up to 4 evenly spaced inner pages with compressed JPEG thumbnails."""
    pages_with_imgs = [pg for pg in (book.get("pages") or []) if pg.get("img")]
    if not pages_with_imgs:
        return []
    if len(pages_with_imgs) <= max_previews:
        chosen = pages_with_imgs
    else:
        indices = sorted({
            round(i * (len(pages_with_imgs) - 1) / (max_previews - 1))
            for i in range(max_previews)
        })
        chosen = [pages_with_imgs[i] for i in indices]

    previews: list[dict[str, Any]] = []
    for pg in chosen:
        uri = image_to_data_uri(pg["img"], max_width=360, quality=72)
        if uri:
            previews.append({
                "page": pg["page"],
                "text": pg.get("text") or "",
                "img": uri,
            })
    return previews


def write_awards_csv(
    participants: list[dict[str, Any]],
    awards: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    """Write awards-summary.csv with UTF-8 BOM for on-site physical certificate handwriting."""
    csv_path = output_dir / "awards-summary.csv"
    participant_by_id = {p["id"]: p for p in participants}

    headers = [
        "奖项",
        "奖内序号",
        "总序号",
        "作者/姓名",
        "作品名",
        "总分",
        *DIMENSIONS,
        "评价等级",
        "一句话闪光点/颁奖词",
        "下一步挑战",
        "页数",
        "来源文件",
        "作品ID",
    ]

    rows: list[list[Any]] = []
    overall_idx = 0
    for award in awards:
        award_title = award["title"]
        for in_award_idx, wid in enumerate(award.get("winnerIds", []), start=1):
            p = participant_by_id.get(wid)
            if p is None:
                continue
            overall_idx += 1
            total = compute_total(p["scores"])
            avg = total / len(DIMENSIONS)
            citation = p["comment"] or "；".join(p["strengths"])
            rows.append([
                safe_csv_cell(award_title),
                in_award_idx,
                overall_idx,
                safe_csv_cell(p["author"]),
                safe_csv_cell(p["project"]),
                total,
                *[p["scores"].get(d, 0) for d in DIMENSIONS],
                safe_csv_cell(qualitative_label(avg)),
                safe_csv_cell(citation),
                safe_csv_cell(p["suggestion"]),
                p["page_count"],
                safe_csv_cell(p["source_file"]),
                safe_csv_cell(p["id"]),
            ])

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return csv_path


COMMON_CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  background-color: #F4EFE6;
  background-image:
    radial-gradient(circle at 50% 0%, rgba(115, 87, 255, 0.14) 0%, transparent 42%),
    radial-gradient(circle at 12% 86%, rgba(255, 128, 102, 0.12) 0%, transparent 46%),
    radial-gradient(circle at 88% 84%, rgba(46, 196, 182, 0.12) 0%, transparent 46%),
    radial-gradient(circle at 50% 48%, rgba(214, 168, 60, 0.10) 0%, transparent 58%),
    linear-gradient(180deg, #FBF7F0 0%, #EDE5D7 100%);
  color: #3A335A;
  font-family: "Microsoft YaHei", "PingFang SC", system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
  overflow-x: hidden;
}
#bg-particles { position: fixed; inset: 0; pointer-events: none; z-index: 0; }

.stage {
  position: absolute; top: 0; left: 0; width: 100%; height: 100%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none; transform: scale(0.96);
  transition: opacity 0.6s cubic-bezier(0.22, 1, 0.36, 1), transform 0.6s cubic-bezier(0.22, 1, 0.36, 1);
  z-index: 1;
  padding: clamp(10px, 1.5vh, 18px) clamp(14px, 2.5vw, 32px);
}
.stage.active { opacity: 1; pointer-events: auto; transform: scale(1); }

.stage-header {
  text-align: center; z-index: 2;
  margin-bottom: clamp(6px, 1.2vh, 14px);
  flex-shrink: 0;
}
.site-logos {
  position: absolute;
  top: clamp(12px, 2vh, 24px);
  left: clamp(14px, 2.5vw, 36px);
  display: flex; align-items: center; gap: clamp(0.6rem, 1.2vw, 1rem);
  z-index: 10; pointer-events: none;
}
.site-logo {
  height: clamp(32px, 5vh, 52px);
  width: auto; max-width: 170px;
  object-fit: contain;
  filter: drop-shadow(0 2px 6px rgba(58,51,90,0.18));
}
.event-badge {
  display: inline-flex; align-items: center; gap: 0.4rem;
  color: #B8860B;
  font-size: clamp(0.75rem, 1.3vw, 0.9rem);
  font-weight: 600;
  margin-bottom: 0.35rem;
  background: rgba(200, 144, 26, 0.08);
  border: 1px solid rgba(200, 144, 26, 0.30);
  border-radius: 999px;
  padding: 0.25rem 0.75rem;
}
.home-title {
  font-size: clamp(1.6rem, 3.5vw, 2.4rem);
  font-weight: 800; line-height: 1.15; letter-spacing: 0.04em;
  background: linear-gradient(to right, #9A7416 0%, #C8901A 45%, #9A7416 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  filter: drop-shadow(0 2px 6px rgba(200, 144, 26, 0.18));
  animation: titleFadeIn 0.8s ease-out;
}
.home-subtitle {
  font-size: clamp(0.9rem, 1.5vw, 1.1rem);
  color: rgba(58, 51, 90, 0.65);
  margin-top: 0.25rem;
  animation: titleFadeIn 0.8s ease-out 0.1s both;
}
@keyframes titleFadeIn {
  0% { opacity: 0; transform: translateY(20px); }
  100% { opacity: 1; transform: translateY(0); }
}

.main-area {
  width: 100%; flex: 1; min-height: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  position: relative; z-index: 2;
}
.cards-container {
  display: flex; flex-wrap: nowrap;
  justify-content: center; align-items: center;
  gap: clamp(0.8rem, 2vw, 1.8rem);
  perspective: 1200px;
  width: 100%; max-width: 1380px;
}

.card-wrap {
  width: clamp(260px, 28vw, 370px);
  height: clamp(390px, 62vh, 600px);
  position: relative; cursor: pointer;
  transition: transform 0.25s ease, opacity 0.35s ease;
  flex-shrink: 0;
}
.card-wrap:hover { transform: translateY(-6px); }
.card-inner {
  position: relative; width: 100%; height: 100%;
  transform-style: preserve-3d;
  transition: transform 0.75s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.card-inner.flipped { transform: rotateY(180deg); }
.card-face {
  position: absolute; inset: 0;
  border-radius: clamp(20px, 3vw, 26px);
  backface-visibility: hidden;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: clamp(0.9rem, 2vh, 1.35rem) clamp(0.9rem, 1.8vw, 1.25rem);
  text-align: center; overflow: hidden;
  border: 1.5px solid rgba(58, 51, 90, 0.10);
  background: linear-gradient(158deg, #FFFFFF 0%, #FBF7F2 44%, #F4EFF8 100%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.9),
    0 26px 60px rgba(58, 51, 90, 0.16),
    0 8px 20px rgba(58, 51, 90, 0.10);
}
.card-back { color: #3A335A; }
.card-back::after, .card-front::after {
  content: ''; position: absolute; inset: 9px;
  border: 1px solid rgba(200, 144, 26, 0.22);
  border-radius: 16px; pointer-events: none;
}
.card-front {
  transform: rotateY(180deg);
  color: #3A335A;
  justify-content: flex-start;
  gap: 0.3rem;
}
.card-icon {
  width: clamp(54px, 7.5vh, 74px); height: clamp(54px, 7.5vh, 74px);
  margin-bottom: 0.7rem; flex-shrink: 0;
  filter: drop-shadow(0 4px 8px rgba(58,51,90,0.16));
}
.card-award-name {
  font-size: clamp(1.25rem, 2.3vw, 1.85rem); font-weight: 800;
  margin-bottom: 0.35rem; line-height: 1.2; flex-shrink: 0;
}
.card-front .card-icon {
  width: clamp(32px, 4.5vh, 42px); height: clamp(32px, 4.5vh, 42px);
  margin-bottom: 0.05rem;
}
.card-front .card-award-name {
  font-size: clamp(1.02rem, 1.8vw, 1.35rem);
  margin-bottom: 0.05rem;
}
.card-count-pill {
  font-size: 0.72rem; font-weight: 600;
  color: rgba(58, 51, 90, 0.62);
  background: rgba(58, 51, 90, 0.06);
  border-radius: 999px;
  padding: 0.12rem 0.55rem;
  flex-shrink: 0;
}
.card-hint {
  position: absolute; bottom: clamp(0.7rem, 1.8vh, 1.1rem); left: 50%;
  transform: translateX(-50%); font-size: 0.78rem;
  opacity: 0.7; color: rgba(58,51,90,0.55); white-space: nowrap;
}

.card-wrap[data-theme="purple"] .card-face {
  border-color: rgba(123, 92, 255, 0.45);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 26px 60px rgba(58, 51, 90, 0.16), 0 10px 30px rgba(115, 87, 255, 0.20);
}
.card-wrap[data-theme="purple"] .card-back,
.card-wrap[data-theme="purple"] .card-front {
  background:
    radial-gradient(circle at 50% 50%, rgba(115,87,255,0.14) 0%, transparent 46%),
    repeating-radial-gradient(circle at 50% 50%, rgba(115,87,255,0.07) 0px, rgba(115,87,255,0.07) 1px, transparent 1px, transparent 9px),
    linear-gradient(158deg, #FFFFFF, #F6F2FF);
}
.card-wrap[data-theme="purple"] .card-award-name { color: #6B4EFF; }
.card-wrap[data-theme="purple"] .card-icon { color: #7B5CFF; }

.card-wrap[data-theme="coral"] .card-face {
  border-color: rgba(230, 120, 90, 0.45);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 26px 60px rgba(58, 51, 90, 0.16), 0 10px 30px rgba(255, 128, 102, 0.20);
}
.card-wrap[data-theme="coral"] .card-back,
.card-wrap[data-theme="coral"] .card-front {
  background:
    radial-gradient(circle at 50% 50%, rgba(255,128,102,0.14) 0%, transparent 46%),
    repeating-radial-gradient(circle at 50% 50%, rgba(255,128,102,0.07) 0px, rgba(255,128,102,0.07) 1px, transparent 1px, transparent 9px),
    linear-gradient(158deg, #FFFFFF, #FFF4F0);
}
.card-wrap[data-theme="coral"] .card-award-name { color: #E15A28; }
.card-wrap[data-theme="coral"] .card-icon { color: #FF8055; }

.card-wrap[data-theme="teal"] .card-face {
  border-color: rgba(30, 180, 158, 0.45);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.9), 0 26px 60px rgba(58, 51, 90, 0.16), 0 10px 30px rgba(46, 196, 182, 0.20);
}
.card-wrap[data-theme="teal"] .card-back,
.card-wrap[data-theme="teal"] .card-front {
  background:
    radial-gradient(circle at 50% 50%, rgba(46,196,182,0.14) 0%, transparent 46%),
    repeating-radial-gradient(circle at 50% 50%, rgba(46,196,182,0.07) 0px, rgba(46,196,182,0.07) 1px, transparent 1px, transparent 9px),
    linear-gradient(158deg, #FFFFFF, #EEFAF7);
}
.card-wrap[data-theme="teal"] .card-award-name { color: #118A75; }
.card-wrap[data-theme="teal"] .card-icon { color: #1FB39B; }

.winner-list-wrap {
  position: relative; width: 100%; flex: 1 1 auto; min-height: 0;
  display: flex; flex-direction: column; margin-top: 0.15rem;
}
.winner-list-wrap::after {
  content: ''; position: absolute; left: 0; right: 8px; bottom: 0; height: 28px;
  background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(251,247,242,0.94));
  pointer-events: none; opacity: 0; transition: opacity 0.2s ease; border-radius: 0 0 12px 12px;
}
.winner-list-wrap.can-scroll::after { opacity: 1; }
.winner-list {
  width: 100%; flex: 1 1 auto; min-height: 0;
  display: flex; flex-direction: column; gap: 0.28rem;
  overflow-y: auto; padding-right: 0.25rem;
  scrollbar-width: thin;
  scrollbar-color: rgba(58,51,90,0.34) rgba(58,51,90,0.06);
}
.winner-list::-webkit-scrollbar { width: 6px; }
.winner-list::-webkit-scrollbar-track { background: rgba(58,51,90,0.06); border-radius: 999px; }
.winner-list::-webkit-scrollbar-thumb { background: rgba(58,51,90,0.30); border-radius: 999px; }
.winner-list::-webkit-scrollbar-thumb:hover { background: rgba(58,51,90,0.48); }
.winner-item {
  width: 100%; display: flex; align-items: center; gap: 0.55rem;
  border: 1px solid rgba(58, 51, 90, 0.12);
  border-radius: 12px; background: rgba(255, 255, 255, 0.78);
  color: #3A335A; padding: 0.30rem 0.54rem;
  text-align: left; cursor: pointer; flex-shrink: 0;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}
.winner-item:hover, .winner-item:focus-visible {
  background: rgba(200, 144, 26, 0.16);
  border-color: rgba(200, 144, 26, 0.50);
  transform: translateY(-1px); outline: none;
}
.winner-item-cover {
  width: 28px; height: 37px; border-radius: 5px;
  object-fit: cover; flex-shrink: 0;
  border: 1px solid rgba(58, 51, 90, 0.14);
  background: rgba(58, 51, 90, 0.06);
}
.winner-item-text { min-width: 0; flex: 1; }
.winner-item-name {
  display: block; font-size: 0.86rem; font-weight: 800; line-height: 1.2;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.winner-item-project {
  display: block; margin-top: 0.08rem;
  color: rgba(58, 51, 90, 0.65); font-size: 0.72rem; line-height: 1.2;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.winner-list-empty { color: rgba(58, 51, 90, 0.55); font-size: 0.9rem; padding: 0.8rem 0; }
.scroll-more-hint {
  display: none; align-items: center; justify-content: center; gap: 0.25rem;
  font-size: 0.70rem; font-weight: 700; color: #9A7416;
  background: rgba(200, 144, 26, 0.12); border: 1px solid rgba(200, 144, 26, 0.32);
  border-radius: 999px; padding: 0.14rem 0.65rem;
  margin-top: 0.1rem; flex-shrink: 0;
}
.card-front.has-more .scroll-more-hint { display: inline-flex; }
.card-hint-front {
  font-size: 0.72rem; opacity: 0.75; color: rgba(58,51,90,0.52);
  padding-top: 0.16rem; flex-shrink: 0;
}

.confetti {
  position: fixed; width: 10px; height: 10px; pointer-events: none; z-index: 50;
  animation: confettiFall 2.4s ease-out forwards;
}
@keyframes confettiFall {
  0% { transform: translateY(-10vh) rotate(0deg); opacity: 1; }
  100% { transform: translateY(110vh) rotate(720deg); opacity: 0; }
}

.detail-stage {
  position: fixed; inset: 0; z-index: 40;
  display: flex; align-items: center; justify-content: center;
  background: rgba(54, 48, 82, 0.36);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  opacity: 0; pointer-events: none;
  transition: opacity 0.4s ease;
  padding: clamp(14px, 2.5vw, 36px);
}
.detail-stage.active { opacity: 1; pointer-events: auto; }
.detail-card {
  position: relative;
  background: linear-gradient(145deg, #FFFFFF, #FBF7F0);
  color: #3A335A; border-radius: 26px;
  padding: clamp(1.3rem, 3.2vw, 2.4rem);
  max-width: 820px; width: 100%; max-height: 90vh; overflow-y: auto;
  border: 1px solid rgba(58, 51, 90, 0.10);
  box-shadow: 0 30px 80px rgba(58, 51, 90, 0.24);
  transform: translateY(18px) scale(0.96); opacity: 0;
  transition: transform 0.45s cubic-bezier(0.22,1,0.36,1) 0.05s, opacity 0.45s ease 0.05s;
}
.detail-stage.active .detail-card { transform: translateY(0) scale(1); opacity: 1; }
.detail-close {
  position: absolute; top: 16px; right: 16px;
  width: 36px; height: 36px; border-radius: 50%;
  border: 1px solid rgba(58,51,90,0.14); background: rgba(255,255,255,0.85);
  color: #3A335A; font-size: 1.05rem; cursor: pointer;
}
.detail-close:hover { background: rgba(200,144,26,0.16); }
.detail-header { display: flex; flex-direction: column; align-items: center; text-align: center; margin-bottom: 1.1rem; }
.detail-header svg { width: 48px; height: 48px; margin-bottom: 0.35rem; color: #3A335A; }
.detail-award {
  display: inline-block;
  background: linear-gradient(145deg, #FFD66B, #FFA62B);
  color: #10142F; padding: 0.32rem 0.9rem; border-radius: 999px;
  font-weight: 700; font-size: 0.92rem; margin-bottom: 0.55rem;
}
.detail-title { font-size: clamp(1.5rem, 4vw, 2.15rem); font-weight: 800; }
.detail-project { font-size: clamp(1rem, 2.5vw, 1.25rem); color: rgba(58,51,90,0.68); margin-top: 0.25rem; }
.detail-meta { font-size: 0.82rem; color: rgba(58,51,90,0.52); margin-top: 0.25rem; }

.detail-gallery {
  display: flex; flex-direction: column; gap: 0.9rem;
  margin-bottom: 1.1rem;
}
.detail-cover-frame {
  display: flex; justify-content: center;
  background: rgba(58, 51, 90, 0.04);
  border: 1px solid rgba(58, 51, 90, 0.08);
  border-radius: 16px; padding: 0.75rem;
}
.detail-cover-frame img {
  max-height: 300px; max-width: 100%; width: auto; height: auto;
  border-radius: 10px; box-shadow: 0 10px 26px rgba(58, 51, 90, 0.16);
  object-fit: contain; cursor: zoom-in;
}
.detail-pages-strip {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.65rem;
}
.detail-page-thumb {
  background: rgba(255,255,255,0.8);
  border: 1px solid rgba(58, 51, 90, 0.10);
  border-radius: 12px; padding: 0.45rem;
  display: flex; flex-direction: column; gap: 0.35rem;
  cursor: zoom-in; text-align: left;
}
.detail-page-thumb:hover { border-color: rgba(200,144,26,0.5); }
.detail-page-thumb img {
  width: 100%; aspect-ratio: 3 / 4; object-fit: cover; border-radius: 8px;
  background: rgba(58,51,90,0.05);
}
.detail-page-tag {
  font-size: 0.72rem; font-weight: 700; color: #9A7416;
}
.detail-page-cap {
  font-size: 0.74rem; line-height: 1.35; color: rgba(58,51,90,0.75);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

.detail-score {
  display: flex; align-items: center; justify-content: center; gap: 1rem;
  margin: 0.9rem 0 1.1rem; flex-wrap: wrap;
}
.score-big {
  font-size: clamp(2.8rem, 8vw, 4rem); font-weight: 800; line-height: 1;
  background: linear-gradient(to bottom, #C8901A, #9A7416);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.score-big span { font-size: 0.45em; color: rgba(58,51,90,0.55); -webkit-text-fill-color: rgba(58,51,90,0.55); }
.score-badge {
  background: rgba(200, 144, 26, 0.12); border: 1px solid rgba(200, 144, 26, 0.35);
  color: #9A7416; padding: 0.4rem 0.9rem; border-radius: 999px; font-weight: 700; font-size: 0.95rem;
}
.detail-strengths, .detail-suggestion, .detail-dimensions { margin-bottom: 1rem; }
.detail-strengths h4, .detail-suggestion h4 { font-size: 1.05rem; margin-bottom: 0.55rem; color: #9A7416; }
.detail-strengths ul { list-style: none; display: flex; flex-direction: column; gap: 0.4rem; }
.detail-strengths li {
  background: rgba(58,51,90,0.04); border: 1px solid rgba(58,51,90,0.08);
  border-radius: 12px; padding: 0.55rem 0.85rem; line-height: 1.45;
}
.detail-suggestion p {
  background: rgba(46, 196, 182, 0.08); border: 1px solid rgba(46, 196, 182, 0.22);
  border-radius: 12px; padding: 0.75rem 0.95rem; line-height: 1.55;
}
.detail-dimensions {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.5rem;
}
.detail-dimension {
  display: flex; align-items: center; justify-content: space-between; gap: 0.65rem;
  background: rgba(200, 144, 26, 0.06); border: 1px solid rgba(200, 144, 26, 0.18);
  border-radius: 10px; padding: 0.5rem 0.75rem; color: rgba(58, 51, 90, 0.86); font-size: 0.85rem;
}
.detail-dimension-score { color: #9A7416; font-weight: 800; white-space: nowrap; }
.back-btn {
  margin-top: 0.4rem; padding: 0.68rem 1.8rem; border: none; border-radius: 999px;
  background: linear-gradient(145deg, #FFD66B, #FFA62B); color: #10142F;
  font-size: 0.98rem; font-weight: 700; cursor: pointer;
  box-shadow: 0 4px 16px rgba(255, 214, 107, 0.3);
  transition: transform 0.18s, box-shadow 0.18s;
}
.back-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 22px rgba(255, 214, 107, 0.45); }

.lightbox {
  position: fixed; inset: 0; z-index: 60;
  background: rgba(16, 20, 47, 0.82);
  display: none; flex-direction: column; align-items: center; justify-content: center;
  padding: 24px; gap: 12px;
}
.lightbox.open { display: flex; }
.lightbox img { max-width: 90vw; max-height: 78vh; border-radius: 12px; box-shadow: 0 18px 50px rgba(0,0,0,0.45); }
.lightbox p { color: #FFF8EC; font-size: 0.95rem; max-width: 720px; text-align: center; line-height: 1.5; }

.bgm-toggle {
  position: fixed; right: clamp(16px, 3vw, 34px); bottom: clamp(16px, 3vh, 30px);
  z-index: 50; width: 50px; height: 50px; border-radius: 50%;
  border: 2px solid rgba(184, 134, 11, 0.55); background: rgba(255, 252, 246, 0.92);
  color: #B8860B; cursor: pointer; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 16px rgba(58, 51, 90, 0.18);
  transition: transform 0.2s ease, box-shadow 0.2s ease; backdrop-filter: blur(4px);
}
.bgm-toggle:hover { transform: translateY(-2px); box-shadow: 0 6px 22px rgba(200, 144, 26, 0.35); }
.bgm-toggle svg { width: 22px; height: 22px; }
.bgm-toggle .icon-pause { display: none; }
.bgm-toggle.playing .icon-pause { display: block; }
.bgm-toggle.playing .icon-note { display: none; }
.bgm-toggle.playing {
  background: linear-gradient(135deg, #FFD66B, #E8A93C);
  color: #5C4308; border-color: rgba(184, 134, 11, 0.8);
}

@media (max-height: 820px) {
  .home-title { font-size: clamp(1.45rem, 3vw, 2.05rem); }
  .card-wrap { width: clamp(245px, 26.5vw, 330px); height: clamp(360px, 64vh, 505px); }
  .card-icon { width: clamp(44px, 6.5vh, 60px); height: clamp(44px, 6.5vh, 60px); }
  .card-front .card-icon { width: clamp(28px, 4vh, 36px); height: clamp(28px, 4vh, 36px); }
}

@media (max-width: 900px) {
  html, body { overflow-y: auto; }
  .stage { position: relative; min-height: 100vh; height: auto; padding: 14px 16px; }
  .cards-container { flex-wrap: wrap; gap: 1rem; }
  .card-wrap { width: min(100%, 380px); height: clamp(420px, 66vh, 520px); }
}
"""

COMMON_BG_JS = r"""
function initBackground() {
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.id = 'bg-particles';
  svg.setAttribute('viewBox', '0 0 100 100');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid slice');
  const defs = document.createElementNS(svgNS, 'defs');
  defs.innerHTML = `
    <filter id="particleGlow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="0.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <radialGradient id="centerGlow" cx="50%" cy="50%" r="70%">
      <stop offset="0%" stop-color="#7357FF" stop-opacity="0.10"/>
      <stop offset="45%" stop-color="#FF8066" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="#10142F" stop-opacity="0"/>
    </radialGradient>
  `;
  svg.appendChild(defs);
  const glowRect = document.createElementNS(svgNS, 'rect');
  glowRect.setAttribute('x', '0'); glowRect.setAttribute('y', '0');
  glowRect.setAttribute('width', '100'); glowRect.setAttribute('height', '100');
  glowRect.setAttribute('fill', 'url(#centerGlow)');
  svg.appendChild(glowRect);
  const colors = ['#FFD66B', '#FF8066', '#7357FF'];
  for (let i = 0; i < 18; i++) {
    const x = 2 + Math.random() * 96;
    const y = 5 + Math.random() * 90;
    const r = 0.15 + Math.random() * 0.55;
    const delay = Math.random() * 7;
    const duration = 8 + Math.random() * 6;
    const rise = 12 + Math.random() * 12;
    const circle = document.createElementNS(svgNS, 'circle');
    circle.setAttribute('cx', x); circle.setAttribute('cy', y); circle.setAttribute('r', r);
    circle.setAttribute('fill', colors[i % colors.length]); circle.setAttribute('opacity', '0');
    circle.setAttribute('filter', 'url(#particleGlow)');
    const animY = document.createElementNS(svgNS, 'animate');
    animY.setAttribute('attributeName', 'cy');
    animY.setAttribute('values', `${y};${Math.max(2, y - rise)};${y}`);
    animY.setAttribute('dur', `${duration}s`); animY.setAttribute('repeatCount', 'indefinite'); animY.setAttribute('begin', `${delay}s`);
    const animOp = document.createElementNS(svgNS, 'animate');
    animOp.setAttribute('attributeName', 'opacity');
    animOp.setAttribute('values', '0;0.25;0');
    animOp.setAttribute('dur', `${duration}s`); animOp.setAttribute('repeatCount', 'indefinite'); animOp.setAttribute('begin', `${delay}s`);
    circle.append(animY, animOp);
    svg.appendChild(circle);
  }
  document.body.appendChild(svg);
}
initBackground();
"""

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{PAGE_TITLE}} {{PAGE_SUBTITLE}}</title>
<style>
{{COMMON_CSS}}
</style>
</head>
<body>
{{AUDIO_TAG}}
<div id="home" class="stage active">
  {{SITE_LOGOS}}
  <header class="stage-header">
    <div class="event-badge">
      <svg width="16" height="16" viewBox="0 0 64 64" style="vertical-align:-3px">
        <path d="M16 12 L48 12 L48 18 C48 30 40 38 32 38 C24 38 16 30 16 18 Z" fill="currentColor"/>
        <rect x="28" y="38" width="8" height="10" fill="currentColor"/>
        <rect x="22" y="48" width="20" height="4" rx="2" fill="currentColor"/>
      </svg>
      {{EVENT_LABEL}}
    </div>
    <h1 class="home-title">{{PAGE_TITLE}}</h1>
    <h2 class="home-subtitle">{{PAGE_SUBTITLE}}</h2>
  </header>

  <main class="main-area">
    <div class="cards-container" id="cardsContainer"></div>
  </main>
</div>

<div id="detail" class="detail-stage">
  <div class="detail-card" id="detailCard">
    <button type="button" class="detail-close" id="detailCloseBtn" aria-label="关闭详情">✕</button>
    <div class="detail-header">
      <svg viewBox="0 0 64 64" id="detailIcon"><use href="#icon-book"></use></svg>
      <div class="detail-award" id="detailAward">奖项</div>
      <div class="detail-title" id="detailAuthor">作者</div>
      <div class="detail-project" id="detailProject">作品</div>
      <div class="detail-meta" id="detailMeta"></div>
    </div>

    <div class="detail-gallery" id="detailGallery" hidden>
      <div class="detail-cover-frame" id="detailCoverWrap" hidden>
        <img id="detailCover" alt="绘本封面">
      </div>
      <div class="detail-pages-strip" id="detailPagesStrip" hidden></div>
    </div>

    <div class="detail-score">
      <div class="score-big" id="detailScore">0<span>/100</span></div>
      <div class="score-badge" id="detailLabel">作品评价</div>
    </div>

    <div class="detail-strengths">
      <h4>🌟 作品闪光点</h4>
      <ul id="detailStrengths"></ul>
    </div>
    <div class="detail-suggestion">
      <h4>🚀 下一步挑战</h4>
      <p id="detailSuggestion">建议</p>
    </div>
    <div class="detail-dimensions" id="detailDimensions"></div>
    <div style="text-align:center">
      <button type="button" class="back-btn" id="backBtn">← 返回颁奖台</button>
    </div>
  </div>
</div>

<div id="lightbox" class="lightbox" role="dialog" aria-modal="true">
  <img id="lightboxImg" alt="绘本页面放大预览">
  <p id="lightboxCap"></p>
</div>

<script>
const AWARDS = {{AWARD_DATA}};
const cardsContainer = document.getElementById('cardsContainer');
const detailStage = document.getElementById('detail');
const lightbox = document.getElementById('lightbox');
let isRevealing = false;

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function createSvgSprite() {
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.style.display = 'none';
  svg.innerHTML = `
    <symbol id="icon-book" viewBox="0 0 64 64">
      <path d="M10 16 C18 12 26 14 32 19 C38 14 46 12 54 16 L54 48 C46 44 38 46 32 51 C26 46 18 44 10 48 Z" fill="currentColor" opacity="0.22"/>
      <path d="M10 16 C18 12 26 14 32 19 L32 51 C26 46 18 44 10 48 Z M54 16 C46 12 38 14 32 19 L32 51 C38 46 46 44 54 48 Z" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linejoin="round"/>
      <path d="M32 10 L34.2 14.5 L39 15.2 L35.5 18.6 L36.4 23.4 L32 21.1 L27.6 23.4 L28.5 18.6 L25 15.2 L29.8 14.5 Z" fill="#FFD66B"/>
    </symbol>
    <symbol id="icon-palette" viewBox="0 0 64 64">
      <path d="M32 10 C19 10 10 19 10 31 C10 43 19 52 31 52 C36 52 39 49 38 45 C37.2 42.2 39.2 40 42 40 L46 40 C51 40 54 36.5 54 31.5 C54 19.5 44.5 10 32 10 Z" fill="currentColor" opacity="0.22" stroke="currentColor" stroke-width="3"/>
      <circle cx="22" cy="26" r="3.2" fill="#FF8066"/>
      <circle cx="31" cy="20" r="3.2" fill="#FFD66B"/>
      <circle cx="42" cy="24" r="3.2" fill="#7357FF"/>
      <circle cx="21" cy="37" r="3.2" fill="#2EC4B6"/>
    </symbol>
    <symbol id="icon-sparkles" viewBox="0 0 64 64">
      <path d="M32 8 L36.5 23.5 L52 28 L36.5 32.5 L32 48 L27.5 32.5 L12 28 L27.5 23.5 Z" fill="currentColor" opacity="0.25" stroke="currentColor" stroke-width="2.8" stroke-linejoin="round"/>
      <path d="M48 10 L49.8 15.2 L55 17 L49.8 18.8 L48 24 L46.2 18.8 L41 17 L46.2 15.2 Z" fill="#FFD66B"/>
      <path d="M16 42 L17.5 46 L21.5 47.5 L17.5 49 L16 53 L14.5 49 L10.5 47.5 L14.5 46 Z" fill="#FF8066"/>
    </symbol>
  `;
  document.body.appendChild(svg);
}

function createConfetti() {
  const colors = ['#FFD66B', '#FF8066', '#7357FF', '#2EC4B6', '#F8F7FF'];
  for (let i = 0; i < 28; i++) {
    const c = document.createElement('div');
    c.className = 'confetti';
    c.style.left = (10 + Math.random() * 80) + 'vw';
    c.style.background = colors[Math.floor(Math.random() * colors.length)];
    c.style.animationDuration = (1.8 + Math.random() * 0.6) + 's';
    c.style.transform = `rotate(${Math.random() * 360}deg)`;
    document.body.appendChild(c);
    setTimeout(() => c.remove(), 2600);
  }
}

function openLightbox(src, caption) {
  document.getElementById('lightboxImg').src = src;
  document.getElementById('lightboxCap').textContent = caption || '';
  lightbox.classList.add('open');
}
function closeLightbox() {
  lightbox.classList.remove('open');
}
lightbox.addEventListener('click', closeLightbox);

function showDetail(awardIndex, winnerIndex) {
  const award = AWARDS[awardIndex];
  const data = award && award.winners ? award.winners[winnerIndex] : null;
  if (!award || !data) return;

  const iconName = ['book', 'palette', 'sparkles'].includes(award.icon) ? award.icon : 'book';
  document.getElementById('detailIcon').innerHTML = `<use href="#icon-${iconName}"></use>`;
  document.getElementById('detailAward').textContent = award.award;
  document.getElementById('detailAuthor').textContent = data.author;
  document.getElementById('detailProject').textContent = '《' + data.project + '》';
  document.getElementById('detailMeta').textContent = data.pageCount ? ('共 ' + data.pageCount + ' 页内页') : '';

  const gallery = document.getElementById('detailGallery');
  const coverWrap = document.getElementById('detailCoverWrap');
  const coverImg = document.getElementById('detailCover');
  const strip = document.getElementById('detailPagesStrip');
  let hasMedia = false;

  if (data.cover) {
    coverImg.src = data.cover;
    coverImg.alt = data.project + ' 封面';
    coverImg.onclick = () => openLightbox(data.cover, '《' + data.project + '》封面');
    coverWrap.hidden = false;
    hasMedia = true;
  } else {
    coverImg.removeAttribute('src');
    coverImg.onclick = null;
    coverWrap.hidden = true;
  }

  strip.innerHTML = '';
  const previews = data.previews || [];
  if (previews.length) {
    previews.forEach(pg => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'detail-page-thumb';
      const im = document.createElement('img');
      im.src = pg.img;
      im.alt = '第 ' + pg.page + ' 页';
      const tag = document.createElement('span');
      tag.className = 'detail-page-tag';
      tag.textContent = '第 ' + pg.page + ' 页';
      const cap = document.createElement('span');
      cap.className = 'detail-page-cap';
      cap.textContent = pg.text || '点击放大查看画面';
      btn.append(im, tag, cap);
      btn.addEventListener('click', () => openLightbox(pg.img, '第 ' + pg.page + ' 页：' + (pg.text || '')));
      strip.appendChild(btn);
    });
    strip.hidden = false;
    hasMedia = true;
  } else {
    strip.hidden = true;
  }
  gallery.hidden = !hasMedia;

  document.getElementById('detailScore').innerHTML = data.total + '<span>/100</span>';
  document.getElementById('detailLabel').textContent = data.label;

  const strengthList = document.getElementById('detailStrengths');
  strengthList.innerHTML = '';
  (data.strengths || []).forEach(s => {
    const li = document.createElement('li');
    li.textContent = s;
    strengthList.appendChild(li);
  });

  document.getElementById('detailSuggestion').textContent = data.suggestion;
  const dimensions = document.getElementById('detailDimensions');
  dimensions.innerHTML = '';
  (data.dimensions || []).forEach(dim => {
    const row = document.createElement('div');
    row.className = 'detail-dimension';
    const name = document.createElement('span');
    name.textContent = dim.name;
    const score = document.createElement('span');
    score.className = 'detail-dimension-score';
    score.textContent = dim.score + '/20';
    row.append(name, score);
    dimensions.appendChild(row);
  });

  document.getElementById('detailCard').scrollTop = 0;
  detailStage.classList.add('active');
}

function hideDetail() {
  closeLightbox();
  detailStage.classList.remove('active');
}

function createCard(award, index) {
  const wrap = document.createElement('div');
  wrap.className = 'card-wrap';
  wrap.id = 'card-' + index;
  wrap.dataset.theme = award.theme;
  wrap.setAttribute('aria-label', award.award + '，点击揭晓获奖作品');

  const iconName = ['book', 'palette', 'sparkles'].includes(award.icon) ? award.icon : 'book';
  wrap.innerHTML = `
    <div class="card-inner">
      <div class="card-face card-back">
        <svg class="card-icon"><use href="#icon-${iconName}"></use></svg>
        <div class="card-award-name">${escapeHtml(award.award)}</div>
        <div class="card-hint">点击揭晓</div>
      </div>
      <div class="card-face card-front">
        <svg class="card-icon"><use href="#icon-${iconName}"></use></svg>
        <div class="card-award-name">${escapeHtml(award.award)}</div>
        <div class="card-count-pill">共 ${award.winners.length} 组作品</div>
        <div class="winner-list-wrap">
          <div class="winner-list" aria-label="${escapeHtml(award.award)}获奖作品名单"></div>
        </div>
        <div class="scroll-more-hint" aria-hidden="true">↓ 下滑查看全部 ${award.winners.length} 组</div>
        <div class="card-hint-front">点击具体绘本查看详情与内页</div>
      </div>
    </div>
  `;

  const cardFront = wrap.querySelector('.card-front');
  const listWrap = wrap.querySelector('.winner-list-wrap');
  const winnerList = wrap.querySelector('.winner-list');
  function updateScrollCue() {
    const canScroll = winnerList.scrollHeight - winnerList.clientHeight > 3;
    const atBottom = winnerList.scrollTop + winnerList.clientHeight >= winnerList.scrollHeight - 4;
    const showMore = canScroll && !atBottom;
    listWrap.classList.toggle('can-scroll', showMore);
    cardFront.classList.toggle('has-more', showMore);
  }
  winnerList.addEventListener('scroll', updateScrollCue, { passive: true });
  window.addEventListener('resize', updateScrollCue);
  requestAnimationFrame(updateScrollCue);
  if (!award.winners.length) {
    const empty = document.createElement('div');
    empty.className = 'winner-list-empty';
    empty.textContent = '暂无获奖作品';
    winnerList.appendChild(empty);
  } else {
    award.winners.forEach((winner, winnerIndex) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'winner-item';
      item.setAttribute('aria-label', winner.author + '，' + winner.project + '，查看详情');
      const author = document.createElement('span');
      author.className = 'winner-item-name';
      author.textContent = winner.author;
      const project = document.createElement('span');
      project.className = 'winner-item-project';
      project.textContent = '《' + winner.project + '》';
      const text = document.createElement('span');
      text.className = 'winner-item-text';
      text.append(author, project);

      if (winner.cover) {
        const thumb = document.createElement('img');
        thumb.className = 'winner-item-cover';
        thumb.src = winner.cover;
        thumb.alt = '';
        item.append(thumb, text);
      } else {
        item.append(text);
      }
      item.addEventListener('click', event => {
        event.stopPropagation();
        showDetail(index, winnerIndex);
      });
      winnerList.appendChild(item);
    });
  }

  wrap.addEventListener('click', () => {
    if (isRevealing) return;
    const inner = wrap.querySelector('.card-inner');
    if (!wrap.classList.contains('flipped')) {
      isRevealing = true;
      wrap.classList.add('flipped');
      inner.classList.add('flipped');
      wrap.setAttribute('aria-label', award.award + '，已揭晓，点击获奖作品查看详情');
      createConfetti();
      setTimeout(updateScrollCue, 60);
      setTimeout(() => { isRevealing = false; }, 760);
    }
  });
  return wrap;
}

document.getElementById('backBtn').addEventListener('click', hideDetail);
document.getElementById('detailCloseBtn').addEventListener('click', hideDetail);
detailStage.addEventListener('click', (e) => { if (e.target === detailStage) hideDetail(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (lightbox.classList.contains('open')) closeLightbox();
    else hideDetail();
  }
});

(function initBgm() {
  const bgm = document.getElementById('bgm');
  const btn = document.getElementById('bgmToggle');
  if (!bgm || !btn) return;
  let playing = false;
  function sync(isPlaying) {
    playing = isPlaying;
    btn.classList.toggle('playing', isPlaying);
    btn.setAttribute('aria-pressed', String(isPlaying));
  }
  function removeGestureListeners() {
    document.removeEventListener('pointerdown', onFirstGesture);
    document.removeEventListener('keydown', onFirstGesture);
  }
  function startPlayback() {
    if (playing) return;
    bgm.play().then(() => {
      sync(true);
      removeGestureListeners();
    }).catch(() => {});
  }
  function onFirstGesture(e) {
    if (btn.contains(e.target)) return;
    startPlayback();
  }
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    removeGestureListeners();
    if (bgm.paused) {
      bgm.play().then(() => sync(true)).catch(() => {});
    } else {
      bgm.pause();
      sync(false);
    }
  });
  startPlayback();
  document.addEventListener('pointerdown', onFirstGesture);
  document.addEventListener('keydown', onFirstGesture);
})();

createSvgSprite();
AWARDS.forEach((award, i) => cardsContainer.appendChild(createCard(award, i)));

{{COMMON_BG_JS}}
</script>
</body>
</html>
"""


def generate_html(
    participants: list[dict[str, Any]],
    awards: list[dict[str, Any]],
    books: list[dict[str, Any]],
    output_dir: Path,
    event_label: str,
    page_title: str,
    page_subtitle: str,
    logo_specs: list[str],
    music_arg: str | None,
    no_music: bool,
) -> Path:
    """Render self-contained offline index.html and normalized scores.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    book_by_id = {b["id"]: b for b in books}
    participant_by_id = {p["id"]: p for p in participants}

    cover_by_id: dict[str, str] = {}
    previews_by_id: dict[str, list[dict[str, Any]]] = {}
    for p in participants:
        b = book_by_id.get(p["id"])
        if not b:
            continue
        cover_src = b.get("cover") or ""
        if not cover_src:
            for pg in b.get("pages") or []:
                if pg.get("img"):
                    cover_src = pg["img"]
                    break
        if cover_src:
            uri = image_to_data_uri(cover_src, max_width=560, quality=76)
            if uri:
                cover_by_id[p["id"]] = uri
        previews = select_preview_pages(b, max_previews=4)
        if previews:
            previews_by_id[p["id"]] = previews

    award_data: list[dict[str, Any]] = []
    for award in awards:
        winners: list[dict[str, Any]] = []
        for wid in award.get("winnerIds", []):
            w = participant_by_id.get(wid)
            if w is None:
                continue
            total = compute_total(w["scores"])
            winners.append({
                "id": w["id"],
                "author": w["author"],
                "project": w["project"],
                "pageCount": w["page_count"],
                "total": total,
                "label": qualitative_label(total / len(DIMENSIONS)),
                "strengths": w["strengths"],
                "suggestion": w["suggestion"],
                "dimensions": [{"name": d, "score": w["scores"].get(d, 0)} for d in DIMENSIONS],
                "cover": cover_by_id.get(w["id"]),
                "previews": previews_by_id.get(w["id"], []),
            })
        award_data.append({
            "award": award["title"],
            "icon": award.get("icon", "book"),
            "theme": award.get("theme", "purple"),
            "winners": winners,
        })

    music_uri = load_music_data(music_arg, no_music)
    audio_tag = ""
    if music_uri:
        audio_tag = (
            f'<audio id="bgm" loop preload="auto" src="{music_uri}"></audio>'
            '<button id="bgmToggle" class="bgm-toggle" type="button"'
            ' aria-label="播放或暂停背景音乐" title="播放 / 暂停背景音乐">'
            '<svg class="icon-note" viewBox="0 0 24 24" fill="currentColor">'
            '<path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 '
            '4-1.79 4-4V7h4V3h-6z"/>'
            '</svg>'
            '<svg class="icon-pause" viewBox="0 0 24 24" fill="currentColor">'
            '<rect x="6" y="4" width="4" height="16" rx="1"/>'
            '<rect x="14" y="4" width="4" height="16" rx="1"/>'
            '</svg>'
            '</button>'
        )

    html = HTML_TEMPLATE
    html = html.replace("{{COMMON_CSS}}", COMMON_CSS)
    html = html.replace("{{AUDIO_TAG}}", audio_tag)
    html = html.replace("{{SITE_LOGOS}}", build_site_logos_html(logo_specs))
    html = html.replace("{{AWARD_DATA}}", json_for_script(award_data))
    html = html.replace("{{COMMON_BG_JS}}", COMMON_BG_JS)
    html = html.replace("{{EVENT_LABEL}}", escape_html(event_label))
    html = html.replace("{{PAGE_TITLE}}", escape_html(page_title))
    html = html.replace("{{PAGE_SUBTITLE}}", escape_html(page_subtitle))

    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")

    scores_backup = {
        "version": 1,
        "event": event_label,
        "dimensions": DIMENSIONS,
        "participants": participants,
        "awards": awards,
    }
    (output_dir / "scores.json").write_text(
        json.dumps(scores_backup, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Judge children's AI picture books and generate an offline 3D award site + CSV summary."
    )
    parser.add_argument("--input", required=True, help="Path to a .zip archive or folder of picture books")
    parser.add_argument("--output", required=True, help="Output directory (must be outside --input)")
    parser.add_argument(
        "--awards",
        default=",".join(DEFAULT_AWARD_TITLES),
        help="Exactly three comma-separated award names (default: 最佳故事奖,最佳画面奖,最佳创意奖)",
    )
    parser.add_argument("--event", default=DEFAULT_EVENT_LABEL, help="Event badge label")
    parser.add_argument("--title", default=DEFAULT_PAGE_TITLE, help="Main ceremony heading")
    parser.add_argument("--subtitle", default=DEFAULT_PAGE_SUBTITLE, help="Ceremony subheading")
    parser.add_argument(
        "--logo",
        action="append",
        default=[],
        help="Optional logo path (or 'path|alt_text'); repeatable, gracefully skipped if missing",
    )
    parser.add_argument("--music", default=None, help="Optional path to custom background MP3")
    parser.add_argument("--no-music", action="store_true", help="Disable background music embedding")
    return parser.parse_args(argv)


def validate_paths(input_path: Path, output_dir: Path) -> None:
    """Prevent output directory from nesting inside input directory (or vice versa)."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")
    if output_dir == input_path or input_path in output_dir.parents:
        raise ValueError("--output must not be the same as or nested inside --input")
    if input_path.is_dir() and output_dir in input_path.parents:
        raise ValueError("--input must not be nested inside --output")


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    args = parse_args(argv)
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()

    award_titles = [a.strip() for a in args.awards.split(",") if a.strip()]
    if len(award_titles) != 3:
        raise ValueError("--awards must contain exactly three non-empty award names")

    validate_paths(input_path, output_dir)

    temp_extracted: Path | None = None
    try:
        if input_path.is_file() and input_path.suffix.lower() == ".zip":
            temp_extracted = extract_zip_safe(input_path)
            scan_path = temp_extracted
        elif input_path.is_dir():
            scan_path = input_path
        else:
            raise ValueError(f"Input must be a .zip file or directory: {input_path}")

        books, global_warnings = discover_books(scan_path)
        if not books:
            detail = f" ({'; '.join(global_warnings)})" if global_warnings else ""
            raise ValueError(f"No valid picture books found in {input_path}{detail}")

        output_dir.mkdir(parents=True, exist_ok=True)
        scores = load_scores(output_dir)

        if scores is None:
            manifest_path = prepare_review_assets(
                books,
                output_dir=output_dir,
                global_warnings=global_warnings,
                event_label=args.event,
                award_titles=award_titles,
            )
            print_discovery_summary(books, output_dir, manifest_path, global_warnings, award_titles)
            return

        participants, awards = normalize_scores(scores, books, award_titles)
        index_path = generate_html(
            participants=participants,
            awards=awards,
            books=books,
            output_dir=output_dir,
            event_label=args.event,
            page_title=args.title,
            page_subtitle=args.subtitle,
            logo_specs=args.logo,
            music_arg=args.music,
            no_music=args.no_music,
        )
        csv_path = write_awards_csv(participants, awards, output_dir)

        print(f"Generated picture book award site: {output_dir}")
        print(f"Home page: {index_path}")
        print(f"Summary CSV: {csv_path}")
        print("\nAwards:")
        p_by_id = {p["id"]: p for p in participants}
        for award in awards:
            winners = [p_by_id[wid] for wid in award.get("winnerIds", []) if wid in p_by_id]
            names = ", ".join(f"{w['author']} - 《{w['project']}》" for w in winners) if winners else "无获奖者"
            print(f"  {award['title']} ({len(winners)}): {names}")
    finally:
        if temp_extracted and temp_extracted.exists():
            shutil.rmtree(temp_extracted, ignore_errors=True)


if __name__ == "__main__":
    main()
