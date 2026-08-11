#!/usr/bin/env python3
"""Replace a QR code region in an image with the user's own QR code, then validate."""

import argparse
import sys
from pathlib import Path
from PIL import Image


def validate_qr(image_path: str) -> tuple[bool, str]:
    """Try to detect and decode QR code in the image. Returns (success, decoded_text)."""
    try:
        import cv2
        img = cv2.imread(image_path)
        if img is None:
            return False, "cannot read image"
        detector = cv2.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(img)
        if data:
            return True, data
        return False, "no QR code detected in the image"
    except Exception as e:
        return False, f"detection error: {e}"


def replace_qr(source: str, qr: str, x: int, y: int, w: int, h: int, output: str | None = None):
    src = Image.open(source).convert("RGBA")
    qr_img = Image.open(qr).convert("RGBA")
    qr_resized = qr_img.resize((w, h), Image.LANCZOS)

    result = src.copy()
    from PIL import ImageDraw
    draw = ImageDraw.Draw(result)
    draw.rectangle([x, y, x + w, y + h], fill="white")
    result.paste(qr_resized, (x, y), qr_resized)

    out_path = output or source
    result.save(out_path)
    print(f"SAVED: {out_path}")

    # Validate the QR code in the output image
    valid, info = validate_qr(out_path)
    if valid:
        print(f"QR_VALID: yes — decoded content: {info}")
    else:
        print(f"QR_VALID: no — {info}")
        print("WARNING: The QR code may not be scannable. Please test it yourself before using.")
    return out_path


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Replace and validate QR code in image")
    p.add_argument("source", help="Source image path")
    p.add_argument("qr", help="Your QR code image path")
    p.add_argument("--x", type=int, required=True, help="X position (left edge)")
    p.add_argument("--y", type=int, required=True, help="Y position (top edge)")
    p.add_argument("--w", type=int, required=True, help="Width of QR area")
    p.add_argument("--h", type=int, required=True, help="Height of QR area")
    p.add_argument("--output", "-o", help="Output path (default: overwrite source)")
    args = p.parse_args()
    replace_qr(args.source, args.qr, args.x, args.y, args.w, args.h, args.output)
