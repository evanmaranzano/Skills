#!/usr/bin/env python3
"""上传公众号封面素材或正文图片。"""

import argparse
import json
import mimetypes
import os
import sys

import requests

from retry_util import request_with_retry
from wechat_errors import format_wechat_api_error, redact_sensitive_text


WECHAT_API = "https://api.weixin.qq.com/cgi-bin"
COVER_IMAGE_TYPES = {".bmp", ".gif", ".jpeg", ".jpg", ".png"}
ARTICLE_IMAGE_TYPES = {".jpeg", ".jpg", ".png"}
ARTICLE_IMAGE_MAX_BYTES = 1024 * 1024
COVER_IMAGE_MAX_BYTES = 10 * 1024 * 1024


def get_access_token(app_id, app_secret):
    """获取微信公众号 access_token。"""
    url = f"{WECHAT_API}/token"
    params = {
        "grant_type": "client_credential",
        "appid": app_id,
        "secret": app_secret,
    }

    try:
        response = request_with_retry("GET", url, params=params, timeout=30)
        if response.status_code >= 400:
            raise Exception(f"获取 access_token 失败：HTTP {response.status_code}")

        data = response.json()
        errcode = data.get("errcode", 0)
        if errcode != 0:
            raise Exception(format_wechat_api_error(errcode, data.get("errmsg")))

        access_token = data.get("access_token")
        if not access_token:
            raise Exception("获取 access_token 失败：响应中没有 access_token")
        return access_token
    except requests.exceptions.RequestException as exc:
        raise Exception(
            f"获取 access_token 失败：{redact_sensitive_text(exc)}"
        ) from exc


def _resolve_credentials(app_id, app_secret):
    if app_id and app_secret:
        return app_id, app_secret

    try:
        from config import get_wechat_config

        config = get_wechat_config()
    except Exception:
        config = {}

    app_id = app_id or config.get("app_id")
    app_secret = app_secret or config.get("app_secret")
    if not app_id or not app_secret:
        raise ValueError(
            "缺少微信公众号配置，请提供 app_id 和 app_secret 参数，或在 .env 文件中配置"
        )
    return app_id, app_secret


def _validate_image(image_path, allowed_types, max_bytes, purpose):
    if not image_path:
        raise ValueError("缺少图片文件路径")
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"图片文件不存在：{image_path}")

    extension = os.path.splitext(image_path)[1].lower()
    if extension not in allowed_types:
        allowed = ", ".join(sorted(allowed_types))
        raise ValueError(f"{purpose}仅支持这些图片格式：{allowed}")

    size = os.path.getsize(image_path)
    if purpose == "封面图" and size > max_bytes:
        raise ValueError(f"封面图大小不能超过 10MB，当前文件为 {size} 字节")
    if purpose == "正文图" and size >= max_bytes:
        raise ValueError(f"正文图大小必须小于 1MB，当前文件为 {size} 字节")


def _post_image(url, access_token, image_path, timeout, query_params=None):
    mime_type = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
    params = {"access_token": access_token}
    if query_params:
        params.update(query_params)
    with open(image_path, "rb") as image_file:
        response = request_with_retry(
            "POST",
            url,
            params=params,
            files={
                "media": (os.path.basename(image_path), image_file, mime_type)
            },
            timeout=timeout,
            max_retries=1,
        )

    if response.status_code >= 400:
        raise Exception(f"图片上传失败：HTTP {response.status_code}")
    return response.json()


def upload_material(app_id=None, app_secret=None, image_path=None):
    """上传永久图片素材，返回用于草稿封面的 media_id。"""
    app_id, app_secret = _resolve_credentials(app_id, app_secret)
    _validate_image(
        image_path,
        COVER_IMAGE_TYPES,
        COVER_IMAGE_MAX_BYTES,
        "封面图",
    )

    access_token = get_access_token(app_id, app_secret)
    data = _post_image(
        f"{WECHAT_API}/material/add_material",
        access_token,
        image_path,
        timeout=60,
        query_params={"type": "image"},
    )
    errcode = data.get("errcode", 0)
    if errcode != 0:
        raise Exception(format_wechat_api_error(errcode, data.get("errmsg")))

    media_id = data.get("media_id")
    if not media_id:
        raise Exception("封面上传失败：微信响应中没有 media_id")

    return {
        "errcode": 0,
        "errmsg": "ok",
        "thumb_media_id": media_id,
        "media_id": media_id,
        "url": data.get("url", ""),
    }


def upload_article_image(app_id=None, app_secret=None, image_path=None):
    """上传正文图片，返回微信正文可用的图片 URL。"""
    app_id, app_secret = _resolve_credentials(app_id, app_secret)
    _validate_image(
        image_path,
        ARTICLE_IMAGE_TYPES,
        ARTICLE_IMAGE_MAX_BYTES,
        "正文图",
    )

    access_token = get_access_token(app_id, app_secret)
    data = _post_image(
        f"{WECHAT_API}/media/uploadimg",
        access_token,
        image_path,
        timeout=60,
    )
    errcode = data.get("errcode", 0)
    if errcode != 0:
        raise Exception(format_wechat_api_error(errcode, data.get("errmsg")))

    image_url = data.get("url")
    if not image_url:
        raise Exception("正文图片上传失败：微信响应中没有 url")

    return {"errcode": 0, "errmsg": "ok", "url": image_url}


def main():
    parser = argparse.ArgumentParser(
        description="上传公众号封面素材或正文图片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--app_id", help="微信公众号 AppID（可从 .env 读取）")
    parser.add_argument("--app_secret", help="微信公众号 AppSecret（可从 .env 读取）")
    parser.add_argument("--image_path", required=True, help="图片文件路径")
    parser.add_argument(
        "--purpose",
        choices=("cover", "body"),
        default="cover",
        help="cover=封面永久素材；body=正文图片 URL",
    )
    args = parser.parse_args()

    try:
        upload = upload_article_image if args.purpose == "body" else upload_material
        result = upload(
            app_id=args.app_id,
            app_secret=args.app_secret,
            image_path=args.image_path,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"错误：{redact_sensitive_text(exc)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
