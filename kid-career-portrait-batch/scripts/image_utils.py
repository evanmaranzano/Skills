#!/usr/bin/env python3
"""Image utilities for kid-career-portrait-batch."""

import base64
import io
import re
from pathlib import Path

from PIL import Image, ImageFilter


def make_output_name(name: str, career: str, suffix: str, fmt: str) -> str:
    """Generate safe output filename."""
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", name)
    safe_career = re.sub(r'[\\/:*?"<>|]', "_", career)
    return f"{safe_name}_{safe_career}_{suffix}.{fmt}"


def parse_size(size: str) -> tuple[int, int] | None:
    if not size or "x" not in size:
        return None
    left, right = size.lower().split("x", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None


def normalize_image_bytes(image_bytes: bytes, target_size: str) -> bytes:
    """Fit image onto target canvas without cropping, using a blurred cover background."""
    size = parse_size(target_size)
    if not size:
        return image_bytes
    target_w, target_h = size
    with Image.open(io.BytesIO(image_bytes)) as src:
        src = src.convert("RGB")
        if src.size == (target_w, target_h):
            out = io.BytesIO()
            src.save(out, format="PNG")
            return out.getvalue()

        bg = src.copy()
        bg_ratio = max(target_w / bg.width, target_h / bg.height)
        bg = bg.resize((round(bg.width * bg_ratio), round(bg.height * bg_ratio)), Image.Resampling.LANCZOS)
        bg_left = (bg.width - target_w) // 2
        bg_top = (bg.height - target_h) // 2
        bg = bg.crop((bg_left, bg_top, bg_left + target_w, bg_top + target_h))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=28))

        fg_ratio = min(target_w / src.width, target_h / src.height)
        fg = src.resize((round(src.width * fg_ratio), round(src.height * fg_ratio)), Image.Resampling.LANCZOS)
        x = (target_w - fg.width) // 2
        y = (target_h - fg.height) // 2
        bg.paste(fg, (x, y))

        out = io.BytesIO()
        bg.save(out, format="PNG")
        return out.getvalue()


def save_image(image_bytes: bytes, path: Path, target_size: str = None) -> None:
    """Save image bytes to file, optionally normalized to a target canvas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if target_size:
        image_bytes = normalize_image_bytes(image_bytes, target_size)
    path.write_bytes(image_bytes)


def normalize_image_file(path: Path, target_size: str) -> bool:
    """Normalize an existing image file in place. Return True if rewritten."""
    size = parse_size(target_size)
    if not size or not path.exists():
        return False
    with Image.open(path) as img:
        if img.size == size:
            return False
    path.write_bytes(normalize_image_bytes(path.read_bytes(), target_size))
    return True


def decode_base64_image(b64_data: str) -> bytes:
    """Decode base64 image data."""
    return base64.b64decode(b64_data)
