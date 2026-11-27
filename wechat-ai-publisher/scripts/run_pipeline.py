#!/usr/bin/env python3
"""
微信公众号发布一站式脚本（run_pipeline）

串联「发布侧」六步：压缩封面 → 上传封面 → 可选上传正文图并替换 → MD 转 HTML → 建草稿 → 归档。
写作（Step 1-2 素材/撰写）仍在对话中由写作 skill 完成，本脚本接管后续机械流程。

用法：
  python3 run_pipeline.py \
    --article article.md \
    --cover   cover.png \
    --title   "文章标题" \
    --author  "作者名" \
    --digest  "摘要（≤50字）" \
    [--theme cyan] \
    [--body-images img1.png,img2.png] \
    [--footer-file footer.md] \
    [--out-dir articles/published] \
    [--app_id ... --app_secret ...]   # 可选，覆盖 .env
"""

import os
import sys
import re
import json
import argparse
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from PIL import Image

# 确保同目录模块可导入（无论从哪个目录运行本脚本）
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

import config
import compress_image
import upload_material
import markdown_to_wechat_doocs
import create_draft
import render_fuzhou_salon
import render_fuzhou_salon30

SALON_THEMES = ("salon", "salon30")


APP_ID = ''
APP_SECRET = ''


def _safe_filename(title):
    """标题转安全文件名（去非法字符，截断 40 字）。"""
    name = re.sub(r'[\\/:*?"<>|]', '', title).strip()
    return name[:40] or 'article'


def _is_external_image_ref(path):
    return bool(re.match(r"(?i)^(?:https?:)?//|data:", path.strip()))


def _is_wechat_image_url(path):
    candidate = path.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    try:
        parsed = urlsplit(candidate)
        hostname = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return hostname == "qpic.cn" or hostname.endswith((".qpic.cn", ".qlogo.cn"))


def _archive_paths(out_dir, title):
    date = datetime.now().strftime('%Y%m%d')
    stem = _safe_filename(title)
    suffix = 1
    while True:
        candidate = stem if suffix == 1 else f"{stem}_{suffix}"
        md_path = out_dir / f"{date}_{candidate}.md"
        meta_path = out_dir / f"{date}_{candidate}_meta.json"
        if not md_path.exists() and not meta_path.exists():
            return md_path, meta_path
        suffix += 1


def _preflight_inputs(args):
    """验证全部本地输入和配置，确保通过后才调用微信写入接口。"""
    args.article = os.path.expanduser(args.article)
    args.cover = os.path.expanduser(args.cover)
    if args.footer_file:
        args.footer_file = os.path.expanduser(args.footer_file)
        if not os.path.isfile(args.footer_file):
            raise FileNotFoundError(f"签名/CTA 文件不存在：{args.footer_file}")

    if not args.title or not args.title.strip():
        raise ValueError("文章标题不能为空")
    if args.digest and len(args.digest.strip()) > 50:
        raise ValueError("摘要不能超过 50 字")
    if not os.path.isfile(args.article):
        raise FileNotFoundError(f"文章不存在：{args.article}")
    if not os.path.isfile(args.cover):
        raise FileNotFoundError(f"封面图片不存在：{args.cover}")

    with open(args.article, 'r', encoding='utf-8') as f:
        md_text = f.read()
    if not md_text.strip():
        raise ValueError("文章内容为空")

    markdown_config = config.get_markdown_config()
    configured_theme = (markdown_config.get('theme') or '').strip()
    theme = args.theme or configured_theme or config.select_theme_by_content(args.title, md_text)
    if theme not in config.SUPPORTED_THEMES:
        supported = ', '.join(config.SUPPORTED_THEMES)
        raise ValueError(f"不支持主题 {theme!r}；可选主题：{supported}")

    extra_images = [
        os.path.expanduser(path.strip())
        for path in args.body_images.split(',')
        if path.strip()
    ]
    if any(_is_external_image_ref(path) for path in extra_images):
        raise ValueError("--body-images 只接受本地文件路径；微信 CDN 地址请直接写在 Markdown 中")

    salon_mod = render_fuzhou_salon30 if theme == "salon30" else render_fuzhou_salon
    _paragraphs, markdown_images = salon_mod.parse_markdown(md_text)
    html_images = re.findall(
        r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']",
        md_text,
        flags=re.IGNORECASE,
    )
    all_image_references = markdown_images + html_images
    unsupported_external = [
        path for path in all_image_references
        if _is_external_image_ref(path) and not _is_wechat_image_url(path)
    ]
    if unsupported_external:
        raise ValueError(
            "微信可能过滤未上传的外链图片；请下载后通过 --body-images 提供本地文件："
            + ", ".join(unsupported_external)
        )

    if theme in SALON_THEMES:
        if not _paragraphs:
            raise ValueError(f"{theme} 模板至少需要一个有效正文段落；引用块内容会按普通段落处理")
        if html_images:
            raise ValueError(f"{theme} 模板请使用 Markdown 图片语法，不支持 HTML <img> 图片")
        local_images = extra_images or [
            path for path in markdown_images if not _is_wechat_image_url(path)
        ]
        if extra_images:
            preflight_text = _replace_local_images(
                md_text, extra_images, upload=False
            )
            _unused, remaining_images = salon_mod.parse_markdown(preflight_text)
            unmatched = [
                path for path in remaining_images
                if not _is_external_image_ref(path)
            ]
            if unmatched:
                raise ValueError(
                    "以下本地图片未通过 --body-images 指定并替换："
                    + ", ".join(unmatched)
                )
    else:
        local_references = [
            path for path in all_image_references
            if not _is_wechat_image_url(path)
        ]
        if not extra_images and local_references:
            raise ValueError(
                "文章包含本地正文图片；请用 --body-images 指定这些图片路径后再运行"
            )
        local_images = extra_images
        if extra_images:
            preflight_text = _replace_local_images(
                md_text, extra_images, upload=False
            )
            _unused, remaining_markdown_images = render_fuzhou_salon.parse_markdown(preflight_text)
            remaining_html_images = re.findall(
                r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']",
                preflight_text,
                flags=re.IGNORECASE,
            )
            remaining_images = remaining_markdown_images + remaining_html_images
            unmatched = [
                path for path in remaining_images
                if not _is_external_image_ref(path)
            ]
            if unmatched:
                raise ValueError(
                    "以下本地图片未通过 --body-images 指定并替换："
                    + ", ".join(unmatched)
                )

    for image_path in local_images:
        if _is_wechat_image_url(image_path):
            continue
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"正文图片不存在或不是本地文件：{image_path}")
    _preflight_body_images(local_images)

    out_dir = Path(os.path.expanduser(args.out_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    if not out_dir.is_dir():
        raise NotADirectoryError(f"归档路径不是目录：{out_dir}")
    md_path, meta_path = _archive_paths(out_dir, args.title)
    return md_text, theme, extra_images, local_images, md_path, meta_path


def _upload_body_image(local_path, index):
    """按微信正文图片限制准备、上传图片，并清理临时转换文件。"""
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"正文图片不存在：{local_path}")

    suffix = Path(local_path).suffix.lower()
    should_compress = (
        suffix not in upload_material.ARTICLE_IMAGE_TYPES
        or os.path.getsize(local_path) >= upload_material.ARTICLE_IMAGE_MAX_BYTES
    )
    upload_path = local_path
    try:
        if should_compress:
            upload_path = os.path.join(
                tempfile.gettempdir(), f"wap_body_{os.getpid()}_{index}.jpg"
            )
            compress_image.compress_image(local_path, upload_path, max_size_kb=900)
            if os.path.getsize(upload_path) >= upload_material.ARTICLE_IMAGE_MAX_BYTES:
                raise ValueError(
                    f"正文图片压缩后仍不小于 1MB，请缩小尺寸或更换图片：{local_path}"
                )

        result = upload_material.upload_article_image(
            app_id=APP_ID, app_secret=APP_SECRET, image_path=upload_path
        )
        image_url = result.get("url")
        if not image_url:
            raise RuntimeError(f"正文图片上传未返回 URL：{local_path}")
        return image_url
    finally:
        if should_compress and os.path.exists(upload_path):
            os.remove(upload_path)


def _image_path_aliases(local_path, basename_counts):
    normalized = local_path.replace("\\", "/")
    aliases = {local_path, normalized}
    if normalized.startswith("./"):
        aliases.add(normalized[2:])
    elif not normalized.startswith("/"):
        aliases.add(f"./{normalized}")

    basename = os.path.basename(normalized)
    if basename_counts.get(basename) == 1:
        aliases.update((basename, f"./{basename}"))
    aliases.update(quote(alias, safe="/:@") for alias in tuple(aliases))
    return sorted(aliases, key=len, reverse=True)


def _replace_image_reference(md_text, alias, url):
    markdown_pattern = re.compile(
        r"(!\[[^\]]*\]\(\s*<?)"
        + re.escape(alias)
        + r"(?=>?\s*(?:\)|[\"']))"
    )
    html_pattern = re.compile(
        r"(<img\b[^>]*?\bsrc\s*=\s*[\"'])"
        + re.escape(alias)
        + r"(?=[\"'])",
        re.IGNORECASE,
    )
    md_text, markdown_count = markdown_pattern.subn(
        lambda match: match.group(1) + url, md_text
    )
    md_text, html_count = html_pattern.subn(
        lambda match: match.group(1) + url, md_text
    )
    return md_text, markdown_count + html_count


def _replace_local_images(md_text, local_paths, upload=True):
    """上传正文图并替换引用；找不到引用时明确失败。"""
    local_paths = list(dict.fromkeys(path.strip() for path in local_paths if path.strip()))
    basenames = [os.path.basename(path.replace("\\", "/")) for path in local_paths]
    basename_counts = {name: basenames.count(name) for name in set(basenames)}

    for index, local in enumerate(local_paths):
        url = (
            _upload_body_image(local, index)
            if upload
            else f"https://preflight.invalid/image-{index}.png"
        )
        original = md_text
        for alias in _image_path_aliases(local, basename_counts):
            md_text, _count = _replace_image_reference(md_text, alias, url)
        if md_text == original:
            raise ValueError(f"正文图片路径未在文章中找到，无法替换：{local}")
        if upload:
            print(
                f"✅ 正文图已上传并替换：{os.path.basename(local)}",
                file=sys.stderr,
            )
    return md_text


def _preflight_body_images(local_images):
    """在第一次微信写入前检查正文图片可读取且压缩后低于 1MB。"""
    for index, local_path in enumerate(local_images):
        if _is_wechat_image_url(local_path):
            continue
        try:
            with Image.open(local_path) as image:
                image.verify()
        except Exception as exc:
            raise ValueError(f"正文图片无法读取：{local_path}：{exc}") from exc

        suffix = Path(local_path).suffix.lower()
        needs_compression = (
            suffix not in upload_material.ARTICLE_IMAGE_TYPES
            or os.path.getsize(local_path) >= upload_material.ARTICLE_IMAGE_MAX_BYTES
        )
        if not needs_compression:
            continue

        temp_path = os.path.join(
            tempfile.gettempdir(), f"wap_preflight_body_{os.getpid()}_{index}.jpg"
        )
        try:
            compress_image.compress_image(local_path, temp_path, max_size_kb=900)
            if os.path.getsize(temp_path) >= upload_material.ARTICLE_IMAGE_MAX_BYTES:
                raise ValueError(
                    f"正文图片压缩后仍不小于 1MB，请缩小尺寸或更换图片：{local_path}"
                )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


def main():
    parser = argparse.ArgumentParser(
        description="微信公众号发布一站式脚本（压缩封面→上传→转HTML→建草稿→归档）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--article', required=True, help='文章 Markdown 路径')
    parser.add_argument('--cover', required=True, help='封面图路径')
    parser.add_argument('--title', required=True, help='文章标题')
    parser.add_argument('--author', default=None, help='作者名（可选）')
    parser.add_argument('--digest', default=None, help='摘要（≤50字，可选）')
    parser.add_argument('--footer-file', default=None, help='显式追加的签名/CTA Markdown 文件')
    parser.add_argument('--theme', choices=config.SUPPORTED_THEMES, default=None,
                        help='主题；优先级高于 .env MARKDOWN_THEME，salon=技术沙龙通稿（21期母版），salon30=亲子活动（智汇对谈第30期版式）')
    parser.add_argument('--body-images', default='',
                        help='正文图路径，逗号分隔，自动上传并替换本地路径')
    parser.add_argument('--out-dir', default=str(SCRIPT_DIR.parent / 'articles' / 'published'),
                        help='归档目录（默认 <skill>/articles/published）')
    parser.add_argument('--app_id', default=None, help='AppID（覆盖 .env）')
    parser.add_argument('--app_secret', default=None, help='AppSecret（覆盖 .env）')
    args = parser.parse_args()

    global APP_ID, APP_SECRET
    cfg = config.get_wechat_config()
    APP_ID = args.app_id or cfg.get('app_id', '')
    APP_SECRET = args.app_secret or cfg.get('app_secret', '')
    if not APP_ID or not APP_SECRET:
        print("错误: 缺少微信公众号配置（请配置 .env 或传 --app_id/--app_secret）", file=sys.stderr)
        sys.exit(1)

    try:
        md_text, theme, extra_images, local_imgs, md_dst, meta_dst = _preflight_inputs(args)
    except (OSError, ValueError) as exc:
        print(f"输入检查失败：{exc}", file=sys.stderr)
        sys.exit(1)

    print(f"🎨 主题：{theme}", file=sys.stderr)

    # 1. 压缩并上传封面（≤800KB）
    cover_out = os.path.join(tempfile.gettempdir(), f"wap_cover_{os.getpid()}.jpg")
    try:
        compress_image.compress_image(args.cover, cover_out, max_size_kb=800)
        print(f"📦 封面已压缩：{cover_out}", file=sys.stderr)
        cover_res = upload_material.upload_material(APP_ID, APP_SECRET, cover_out)
    finally:
        if os.path.exists(cover_out):
            os.remove(cover_out)

    thumb_media_id = cover_res.get('thumb_media_id')
    if not thumb_media_id:
        print(f"错误: 封面上传失败：{cover_res}", file=sys.stderr)
        sys.exit(1)
    print(f"🖼️ 封面上传成功 thumb_media_id={thumb_media_id}", file=sys.stderr)

    # 2. 正文图上传 + 转 HTML
    if theme in SALON_THEMES:
        if local_imgs:
            md_text = _replace_local_images(md_text, local_imgs)
        salon_mod = render_fuzhou_salon30 if theme == "salon30" else render_fuzhou_salon
        html = salon_mod.render(md_text, [])
    else:
        if extra_images:
            md_text = _replace_local_images(md_text, extra_images)
        html = markdown_to_wechat_doocs.markdown_to_html_doocs(md_text, theme)

    # 7. 建草稿
    result = create_draft.create_draft(
        app_id=APP_ID, app_secret=APP_SECRET,
        title=args.title, content=html,
        thumb_media_id=thumb_media_id,
        author=args.author, digest=args.digest,
        footer_file=args.footer_file,
    )
    if result.get('status') != 'success':
        print(f"错误: 建草稿失败：{result}", file=sys.stderr)
        sys.exit(1)
    media_id = result.get('media_id')
    print(f"📝 草稿已创建 media_id={media_id}", file=sys.stderr)

    # 8. 归档；遇到同名文件时使用递增后缀，避免覆盖旧文章
    try:
        with open(md_dst, 'x', encoding='utf-8') as f:
            f.write(md_text)
        with open(meta_dst, 'x', encoding='utf-8') as f:
            json.dump({
                'title': args.title,
                'media_id': media_id,
                'thumb_media_id': thumb_media_id,
                'theme': theme,
                'created_at': datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(
            f"草稿已创建（media_id={media_id}），但归档失败：{exc}。"
            "请勿重新创建草稿；先在公众号后台确认草稿，再手动完成本地归档。",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"📁 已归档：{md_dst}", file=sys.stderr)

    print(f"\n✅ 完成！草稿 media_id={media_id}（默认仅存草稿，群发请在公众号后台确认）")


if __name__ == '__main__':
    main()
