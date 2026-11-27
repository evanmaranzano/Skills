#!/usr/bin/env python3
"""网络请求自动重试工具（指数退避）。

仅对幂等请求的网络异常和 HTTP 5xx 重试；POST 等写入请求只发送一次，
避免请求成功但响应丢失时重复上传素材或创建草稿。4xx 交由调用方处理。
"""

import sys
import time
import requests

from wechat_errors import redact_sensitive_text


def request_with_retry(method, url, max_retries=3, backoff=2, timeout=30, **kwargs):
    """带指数退避的网络请求；非幂等方法最多发送一次。"""
    if method.upper() not in {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}:
        max_retries = 1

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            # 4xx 业务错误不重试，直接交给调用方按 errcode 处理
            if resp.status_code < 500:
                return resp
            last_exc = redact_sensitive_text(
                f"微信服务端错误 HTTP {resp.status_code}: {resp.text[:200]}"
            )
        except requests.exceptions.RequestException as e:
            last_exc = redact_sensitive_text(e)

        if attempt < max_retries:
            wait = backoff ** attempt
            print(
                f"⚠️ 网络请求失败（第 {attempt}/{max_retries} 次），{wait}s 后自动重试：{last_exc}",
                file=sys.stderr,
            )
            time.sleep(wait)

    raise Exception(
        f"网络请求重试 {max_retries} 次仍失败：{last_exc}。"
        f"请检查：①本机网络连接是否正常；②微信 API 服务是否可用；③稍后重试。"
    )
