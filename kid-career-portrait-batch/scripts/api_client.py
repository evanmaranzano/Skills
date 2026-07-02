#!/usr/bin/env python3
"""OpenAI-compatible image edit API client."""

import base64
import logging
import time

import requests

# Retryable HTTP status codes
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ImageEditClient:
    """Client for OpenAI-compatible /v1/images/edits endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        size: str,
        quality: str,
        timeout: int = 300,
        proxies: dict = None,
        fallback_base_url: str = None,
        fallback_api_key: str = None,
        fallback_model: str = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.size = size
        self.quality = quality
        self.timeout = timeout
        self.proxies = proxies
        self.endpoint = self._build_endpoint(self.base_url)
        self.fallback_base_url = fallback_base_url.rstrip("/") if fallback_base_url else None
        self.fallback_api_key = fallback_api_key
        self.fallback_model = fallback_model or model

    @staticmethod
    def _build_endpoint(base_url: str) -> str:
        u = base_url.rstrip("/")
        if u.endswith("/v1"):
            u = u[:-3]
        return f"{u}/v1/images/edits"

    def call(
        self,
        image_path,
        prompt: str,
        logger: logging.Logger,
        retry_times: int,
        backoff: int,
    ) -> dict:
        """Call image edit API with retry and optional fallback.

        Returns dict with keys:
            success(bool), image_bytes(bytes|None), error(str|None), status(int|None)
        """
        result = self._call_once(
            self.endpoint,
            self.api_key,
            self.model,
            image_path,
            prompt,
            logger,
            retry_times,
            backoff,
        )

        if result["success"]:
            return result

        if self.fallback_base_url and self.fallback_api_key:
            logger.warning(
                f"[FALLBACK] primary failed for {image_path.name}, trying fallback API"
            )
            fallback_endpoint = self._build_endpoint(self.fallback_base_url)
            fb_result = self._call_once(
                fallback_endpoint,
                self.fallback_api_key,
                self.fallback_model,
                image_path,
                prompt,
                logger,
                retry_times,
                backoff,
                is_fallback=True,
            )
            if fb_result["success"]:
                return fb_result
            # combine errors so user sees both attempts
            return {
                "success": False,
                "image_bytes": None,
                "error": f"primary: {result.get('error')}; fallback: {fb_result.get('error')}",
                "status": fb_result.get("status") or result.get("status"),
            }

        return result

    def _call_once(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        image_path,
        prompt: str,
        logger: logging.Logger,
        retry_times: int,
        backoff: int,
        is_fallback: bool = False,
    ) -> dict:
        label = "fallback" if is_fallback else "primary"
        for attempt in range(1, retry_times + 1):
            try:
                with open(image_path, "rb") as f:
                    files = {"image": (image_path.name, f, "application/octet-stream")}
                    data = {
                        "model": model,
                        "prompt": prompt,
                        "size": self.size,
                    }
                    if self.quality:
                        data["quality"] = self.quality
                    resp = requests.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {api_key}"},
                        data=data,
                        files=files,
                        timeout=self.timeout,
                        proxies=self.proxies,
                    )
            except requests.exceptions.Timeout:
                logger.warning(
                    f"  [{label}] timeout attempt {attempt}/{retry_times}: {image_path.name}"
                )
                if attempt < retry_times:
                    time.sleep(backoff * attempt)
                    continue
                return {
                    "success": False,
                    "image_bytes": None,
                    "error": "request timeout",
                    "status": None,
                }
            except requests.exceptions.ConnectionError as e:
                logger.warning(
                    f"  [{label}] connection error attempt {attempt}/{retry_times}: {image_path.name}"
                )
                if attempt < retry_times:
                    time.sleep(backoff * attempt)
                    continue
                return {
                    "success": False,
                    "image_bytes": None,
                    "error": f"connection error: {e}",
                    "status": None,
                }

            status = resp.status_code

            if status == 200:
                return self._parse_success(resp, image_path, logger)

            err_msg = self._extract_error(resp)
            if status in RETRYABLE_STATUS and attempt < retry_times:
                wait = backoff * attempt
                logger.warning(
                    f"  HTTP {status} attempt {attempt}/{retry_times}, "
                    f"retrying in {wait}s: {image_path.name}"
                )
                logger.warning(f"    error: {err_msg}")
                time.sleep(wait)
                continue

            return {
                "success": False,
                "image_bytes": None,
                "error": err_msg,
                "status": status,
            }

        return {
            "success": False,
            "image_bytes": None,
            "error": "max retries exceeded",
            "status": None,
        }

    def _parse_success(self, resp, image_path, logger) -> dict:
        try:
            body = resp.json()
        except Exception:
            return {
                "success": False,
                "image_bytes": None,
                "error": "invalid JSON response",
                "status": 200,
            }

        data_list = body.get("data") or body.get("output") or []
        if not data_list:
            # maybe the API returned a direct image
            ct = resp.headers.get("content-type", "")
            if "image" in ct:
                return {
                    "success": True,
                    "image_bytes": resp.content,
                    "error": None,
                    "status": 200,
                }
            return {
                "success": False,
                "image_bytes": None,
                "error": f"no image data in response: {str(body)[:200]}",
                "status": 200,
            }

        item = data_list[0]

        # b64_json
        b64 = item.get("b64_json")
        if b64:
            try:
                img_bytes = base64.b64decode(b64)
                return {
                    "success": True,
                    "image_bytes": img_bytes,
                    "error": None,
                    "status": 200,
                }
            except Exception as e:
                return {
                    "success": False,
                    "image_bytes": None,
                    "error": f"base64 decode failed: {e}",
                    "status": 200,
                }

        # url
        url = item.get("url")
        if url:
            try:
                img_resp = requests.get(url, timeout=120)
                if img_resp.status_code == 200:
                    return {
                        "success": True,
                        "image_bytes": img_resp.content,
                        "error": None,
                        "status": 200,
                    }
                return {
                    "success": False,
                    "image_bytes": None,
                    "error": f"download failed HTTP {img_resp.status_code}",
                    "status": 200,
                }
            except Exception as e:
                return {
                    "success": False,
                    "image_bytes": None,
                    "error": f"download failed: {e}",
                    "status": 200,
                }

        return {
            "success": False,
            "image_bytes": None,
            "error": f"no b64_json or url in response item: {str(item)[:200]}",
            "status": 200,
        }

    @staticmethod
    def _extract_error(resp) -> str:
        try:
            body = resp.json()
            err = body.get("error")
            if isinstance(err, dict):
                return err.get("message", str(err))
            if isinstance(err, str):
                return err
            return str(body)[:300]
        except Exception:
            return resp.text[:300] if resp.text else f"HTTP {resp.status_code}"
