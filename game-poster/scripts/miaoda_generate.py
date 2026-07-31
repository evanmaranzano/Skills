#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
妙搭生图后端调用脚本（仅使用 Python 标准库）

本脚本由 miaoda_image_generator.py 改写，供 game-poster skill 使用：
移除了演示用默认任务，提示词必须通过 --prompt / --tasks-json 传入；
增加 --size 参数以支持竖版海报等尺寸。

网络路线：
    本机 -> https://b5g43k8ysv.aiforce.cloud -> 妙搭生图后端 -> 上游模型

示例：
    python miaoda_generate.py --prompt "..." --size 1024x1792 --output ./poster
    python miaoda_generate.py --prompt "图1" --prompt "图2" --concurrency 2
    python miaoda_generate.py --dry-run --prompt "..."

注意：
    每次调用都是真实生图请求并产生费用。
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as dt
import http.cookiejar
import json
import mimetypes
import os
import re
import statistics
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


# =========================
# 默认配置
# =========================

CONCURRENCY = 3

GENERATION_TIMEOUT_SECONDS = 500
POLL_INTERVAL_SECONDS = 2.0

BASE_URL = "https://b5g43k8ysv.aiforce.cloud/app/app_17aahvuvvmm"
GENERATE_URL = f"{BASE_URL}/api/studio/generate"
PAGE_ROUTE = "/app/app_17aahvuvvmm"

def validate_size(value: str) -> str:
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", value)
    if not match:
        raise SystemExit(
            f"--size 格式无效：{value!r}，应为 宽x高（如 1536x1024、1920x1080）。"
        )
    width, height = int(match.group(1)), int(match.group(2))
    if width % 16 or height % 16:
        raise SystemExit(f"--size 宽高必须是 16 的倍数：{value!r}。")
    if max(width, height) > 3840:
        raise SystemExit(f"--size 最长边不能超过 3840：{value!r}。")
    if width * height < 655_360 or width * height > 8_294_400:
        raise SystemExit(f"--size 总像素超出允许范围：{value!r}。")
    if max(width, height) / min(width, height) > 3:
        raise SystemExit(f"--size 宽高比不能超过 3:1：{value!r}。")
    return value

IMAGE_OPTIONS = {
    "model": "gpt-image-2",
    "quality": "low",
    "n": 1,
    "output_format": "jpeg",
    "output_compression": 80,
    "background": "auto",
    "moderation": "auto",
    "stream": False,
    "partial_images": 0,
}


class MiaodaError(RuntimeError):
    """妙搭调用失败。"""


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if (
            not stream.isatty()
            and hasattr(stream, "reconfigure")
        ):
            stream.reconfigure(encoding="utf-8", errors="replace")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def build_multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----PythonMiaodaBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                ).encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def read_http_error(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", errors="replace")
    except Exception:
        return str(error)


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 35.0,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                int(response.status),
                {key.lower(): value for key, value in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as error:
        detail = read_http_error(error)
        raise MiaodaError(f"HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise MiaodaError(f"网络连接失败：{error.reason}") from error


def initialize_session() -> tuple[dict[str, str], int]:
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar)
    )
    request = urllib.request.Request(
        BASE_URL,
        headers={"Accept": "text/html", "User-Agent": "miaoda-python-client/1.0"},
    )
    try:
        with opener.open(request, timeout=35) as response:
            if response.status != 200:
                raise MiaodaError(f"妙搭页面初始化失败：HTTP {response.status}")
            page_html = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise MiaodaError(
            f"妙搭页面初始化失败：HTTP {error.code}，{read_http_error(error)}"
        ) from error
    except urllib.error.URLError as error:
        raise MiaodaError(f"妙搭页面连接失败：{error.reason}") from error

    csrf_match = re.search(
        r'window\.csrfToken\s*=\s*"([^"]+)"',
        page_html,
        flags=re.IGNORECASE,
    )
    if not csrf_match:
        raise MiaodaError("妙搭页面没有返回 CSRF Token。")

    cookies = [f"{cookie.name}={cookie.value}" for cookie in cookie_jar]
    if not cookies:
        raise MiaodaError("妙搭页面没有返回会话 Cookie。")

    headers = {
        "Accept": "application/json",
        "Cookie": "; ".join(cookies),
        "Referer": BASE_URL,
        "User-Agent": "miaoda-python-client/1.0",
        "X-Page-Route": PAGE_ROUTE,
        "X-Suda-Csrf-Token": csrf_match.group(1),
    }
    return headers, len(cookies)


def image_extension(content_type: str, data: bytes) -> str:
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
    if guessed in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if guessed == ".jpeg" else guessed
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def png_dimensions(data: bytes) -> tuple[int | None, int | None]:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", data[16:24])
    return None, None


def save_image(
    image_object: dict[str, Any],
    task_number: int,
    output_dir: Path,
    common_headers: dict[str, str],
) -> dict[str, Any]:
    data_url = str(image_object.get("dataUrl") or "")
    if not data_url:
        raise MiaodaError("任务已完成，但返回结果中没有 dataUrl。")

    content_type = ""
    data: bytes
    data_match = re.match(
        r"^data:([^;]+);base64,(.+)$",
        data_url,
        flags=re.DOTALL,
    )
    if data_match:
        content_type = data_match.group(1)
        data = base64.b64decode(data_match.group(2), validate=False)
    elif data_url.startswith("https://"):
        _, response_headers, data = http_request(
            data_url,
            headers=common_headers,
            timeout=120,
        )
        content_type = response_headers.get("content-type", "")
    else:
        raise MiaodaError("返回了不支持的图片地址格式。")

    extension = image_extension(content_type, data)
    file_path = output_dir / f"run-{task_number}{extension}"
    file_path.write_bytes(data)
    width, height = png_dimensions(data) if extension == ".png" else (None, None)
    return {
        "file": str(file_path.resolve()),
        "bytes": len(data),
        "width": width,
        "height": height,
        "imageId": image_object.get("id"),
        "revisedPrompt": image_object.get("revisedPrompt"),
    }


class ProgressWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.path.write_text("", encoding="utf-8")

    def write(self, **record: Any) -> None:
        line = json.dumps(
            {"timestamp": now_iso(), **record},
            ensure_ascii=False,
        )
        with self.lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")


def run_one(
    task_number: int,
    task: dict[str, str],
    *,
    common_headers: dict[str, str],
    output_dir: Path,
    progress: ProgressWriter,
    batch_watch_start: float,
    generation_timeout: float,
    image_options: dict[str, Any],
) -> dict[str, Any]:
    started_watch = time.perf_counter()
    result: dict[str, Any] = {
        "run": task_number,
        "name": task["name"],
        "prompt": task["prompt"],
        "quality": image_options["quality"],
        "outputFormat": image_options["output_format"],
        "startedAt": now_iso(),
        "submitOffsetMs": round((started_watch - batch_watch_start) * 1000),
        "createHttpStatus": None,
        "jobCreateSeconds": None,
        "jobId": None,
        "pollCount": 0,
        "success": False,
        "backendGenerationMs": None,
        "usage": None,
        "file": None,
        "bytes": None,
        "width": None,
        "height": None,
        "imageId": None,
        "revisedPrompt": None,
        "totalSeconds": None,
        "finishedAt": None,
        "error": None,
    }
    progress.write(
        event="started",
        run=task_number,
        name=task["name"],
        submitOffsetMs=result["submitOffsetMs"],
    )
    print(f"[{task_number}] 已提交：{task['name']}", flush=True)

    try:
        multipart_body, content_type = build_multipart(
            {
                "prompt": task["prompt"],
                "options": json.dumps(image_options, ensure_ascii=False),
            }
        )
        request_headers = {
            **common_headers,
            "Content-Type": content_type,
            "Content-Length": str(len(multipart_body)),
        }

        create_watch = time.perf_counter()
        create_status, _, create_body = http_request(
            GENERATE_URL,
            method="POST",
            headers=request_headers,
            body=multipart_body,
            timeout=35,
        )
        result["createHttpStatus"] = create_status
        result["jobCreateSeconds"] = round(
            time.perf_counter() - create_watch,
            3,
        )
        create_json = json.loads(create_body.decode("utf-8"))

        immediate_images = create_json.get("images")
        if isinstance(immediate_images, list) and immediate_images:
            result.update(
                save_image(
                    immediate_images[0],
                    task_number,
                    output_dir,
                    common_headers,
                )
            )
            result["success"] = True
            return result

        job_id = str(create_json.get("jobId") or "")
        if not job_id:
            raise MiaodaError("妙搭后端没有返回 jobId。")
        result["jobId"] = job_id
        progress.write(
            event="job_created",
            run=task_number,
            jobId=job_id,
            jobCreateSeconds=result["jobCreateSeconds"],
        )
        print(
            f"[{task_number}] 任务创建成功，等待生成……"
            f"（创建 {result['jobCreateSeconds']:.3f} 秒）",
            flush=True,
        )

        deadline = time.monotonic() + generation_timeout
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_SECONDS)
            result["pollCount"] += 1
            poll_url = f"{GENERATE_URL}/{urllib.parse.quote(job_id, safe='')}"
            _, _, poll_body = http_request(
                poll_url,
                headers=common_headers,
                timeout=35,
            )
            poll_json = json.loads(poll_body.decode("utf-8"))
            status = poll_json.get("status")

            if status == "completed":
                images = poll_json.get("images")
                if not isinstance(images, list) or not images:
                    raise MiaodaError("任务显示完成，但没有返回图片。")
                result.update(
                    save_image(
                        images[0],
                        task_number,
                        output_dir,
                        common_headers,
                    )
                )
                result["backendGenerationMs"] = poll_json.get(
                    "generationDurationMs"
                )
                result["usage"] = poll_json.get("usage")
                result["success"] = True
                return result
            if status == "failed":
                raise MiaodaError(
                    str(poll_json.get("error") or "妙搭后端报告任务失败。")
                )

        raise MiaodaError(
            f"生成超过 {generation_timeout:.0f} 秒，停止等待。"
        )
    except Exception as error:
        result["error"] = str(error)
        return result
    finally:
        result["totalSeconds"] = round(
            time.perf_counter() - started_watch,
            3,
        )
        result["finishedAt"] = now_iso()
        progress.write(
            event="finished",
            run=task_number,
            name=task["name"],
            success=result["success"],
            jobId=result["jobId"],
            totalSeconds=result["totalSeconds"],
            backendGenerationMs=result["backendGenerationMs"],
            file=result["file"],
            error=result["error"],
        )
        outcome = "成功" if result["success"] else f"失败：{result['error']}"
        print(
            f"[{task_number}] {outcome}，等待 {result['totalSeconds']:.3f} 秒",
            flush=True,
        )


def open_in_file_manager(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as error:
        print(f"未能自动打开输出目录：{error}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="通过妙搭生图后端并发生成图片（仅使用Python标准库）。"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=CONCURRENCY,
        help=f"并发数，默认 {CONCURRENCY}。",
    )
    parser.add_argument(
        "--size",
        default="2560x1440",
        help=(
            "图片尺寸 宽x高，默认 2560x1440（16:9 横版封面）；"
            "需为 16 的倍数，常用：1024x1024 方形、1024x1536 竖版、"
            "1536x1024 横版 3:2。"
        ),
    )
    parser.add_argument(
        "--prompt",
        action="append",
        default=None,
        help="提示词；可重复传入多次，每次一张图。必填（除非 --tasks-json）。",
    )
    parser.add_argument(
        "--tasks-json",
        type=Path,
        default=None,
        help="从JSON文件读取任务列表，格式为name和prompt对象数组。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=GENERATION_TIMEOUT_SECONDS,
        help=f"每个任务最长等待秒数，默认 {GENERATION_TIMEOUT_SECONDS}。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="指定输出目录；默认在脚本旁按时间创建。",
    )
    parser.add_argument(
        "--no-open-output",
        action="store_true",
        help="运行结束后不自动打开输出目录。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示配置，不访问网络、不产生费用。",
    )
    return parser


def main() -> int:
    configure_output_encoding()
    args = build_parser().parse_args()
    if args.concurrency < 1:
        raise SystemExit("--concurrency 必须大于等于1。")
    if args.timeout <= 0:
        raise SystemExit("--timeout 必须大于0。")

    image_options = dict(IMAGE_OPTIONS)
    image_options["size"] = validate_size(args.size)

    if args.tasks_json:
        raw_tasks = json.loads(
            args.tasks_json.expanduser().read_text(encoding="utf-8")
        )
        if not isinstance(raw_tasks, list):
            raise SystemExit("--tasks-json 内容必须是JSON数组。")
        tasks = [
            {
                "name": str(item.get("name") or f"JSON任务 {index}"),
                "prompt": str(item.get("prompt") or ""),
            }
            for index, item in enumerate(raw_tasks, start=1)
            if isinstance(item, dict)
        ]
        if any(not task["prompt"].strip() for task in tasks):
            raise SystemExit("--tasks-json 中存在空提示词。")
    elif args.prompt:
        tasks = [
            {"name": f"任务 {index}", "prompt": prompt}
            for index, prompt in enumerate(args.prompt, start=1)
        ]
    else:
        raise SystemExit(
            "请用 --prompt 或 --tasks-json 提供提示词（--dry-run 也需要）。"
        )

    if not tasks:
        raise SystemExit("没有可运行的提示词。")

    print("=" * 60)
    print("妙搭生图后端 Python 客户端")
    print(f"路线：本机 -> {BASE_URL} -> 妙搭后端")
    print(f"模型：{image_options['model']}")
    print(
        f"参数：quality={image_options['quality']}，"
        f"format={image_options['output_format']}，"
        f"size={image_options['size']}"
    )
    print(f"任务数：{len(tasks)}")
    print(f"并发数：{min(args.concurrency, len(tasks))}")
    print(f"单任务超时：{args.timeout:.0f} 秒")
    print("=" * 60)

    for index, task in enumerate(tasks, start=1):
        print(f"{index}. {task['name']}：{task['prompt']}")

    if args.dry_run:
        print("\nDRY RUN：没有访问网络，也没有产生生图费用。")
        return 0

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = (
        args.output.expanduser().resolve()
        if args.output
        else Path(__file__).resolve().parent
        / f"miaoda-python-output-{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    progress = ProgressWriter(output_dir / "progress.ndjson")

    print("\n正在初始化妙搭访问会话……", flush=True)
    try:
        common_headers, cookie_count = initialize_session()
    except Exception as error:
        print(f"初始化失败：{error}", file=sys.stderr)
        return 2
    print(f"会话初始化成功，取得 {cookie_count} 个 Cookie。", flush=True)
    progress.write(
        event="session_initialized",
        sessionCookieCount=cookie_count,
    )

    batch_started_at = now_iso()
    batch_watch_start = time.perf_counter()
    results: list[dict[str, Any]] = []
    worker_count = min(args.concurrency, len(tasks))
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="miaoda",
    ) as executor:
        futures = [
            executor.submit(
                run_one,
                index,
                task,
                common_headers=common_headers,
                output_dir=output_dir,
                progress=progress,
                batch_watch_start=batch_watch_start,
                generation_timeout=args.timeout,
                image_options=image_options,
            )
            for index, task in enumerate(tasks, start=1)
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["run"])
    batch_total_seconds = round(time.perf_counter() - batch_watch_start, 3)
    successful = [item for item in results if item["success"]]
    all_waits = [float(item["totalSeconds"]) for item in results]
    successful_waits = [
        float(item["totalSeconds"]) for item in successful
    ]
    summary = {
        "testedAt": batch_started_at,
        "route": f"local -> {BASE_URL} -> Miaoda backend",
        "proxyEndpoint": GENERATE_URL,
        "model": image_options["model"],
        "requestOptions": image_options,
        "requestedConcurrency": args.concurrency,
        "effectiveConcurrency": worker_count,
        "taskCount": len(results),
        "successCount": len(successful),
        "failureCount": len(results) - len(successful),
        "successRate": len(successful) / len(results),
        "batchTotalSeconds": batch_total_seconds,
        "averageOutcomeSeconds": round(statistics.mean(all_waits), 3),
        "averageSuccessfulSeconds": (
            round(statistics.mean(successful_waits), 3)
            if successful_waits
            else None
        ),
        "medianOutcomeSeconds": round(statistics.median(all_waits), 3),
        "results": results,
    }
    results_path = output_dir / "results.json"
    results_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    progress.write(
        event="all_completed",
        resultsPath=str(results_path.resolve()),
        batchTotalSeconds=batch_total_seconds,
    )

    print("\n" + "=" * 60)
    print(
        f"完成：{len(successful)}/{len(results)} 成功，"
        f"成功率 {summary['successRate'] * 100:.1f}%"
    )
    print(f"整批耗时：{batch_total_seconds:.3f} 秒")
    print(f"平均等待：{summary['averageOutcomeSeconds']:.3f} 秒")
    print(f"结果文件：{results_path.resolve()}")
    print("=" * 60)

    if not args.no_open_output:
        open_in_file_manager(output_dir)
    return 0 if len(successful) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
