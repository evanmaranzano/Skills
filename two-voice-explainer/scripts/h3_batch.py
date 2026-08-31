#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""h3_batch.py — OpenMontage 阶段 2：Molispark Design 工作台（MiniMax-H3）批量视频脚本

红线声明：本脚本只调用 15 上的 Molispark 工作台（默认 http://127.0.0.1:18090），
禁止直连 16 上的 H3 引擎（10.10.127.16:18081）提交任何任务。引擎提交/轮询/下载
全部由工作台后端代为完成，本脚本只是工作台的批量客户端。

执行位置：15 服务器上运行（回环调工作台）。如从其他机器调用，请先建立 SSH 端口转发，将工作台映射到本机 127.0.0.1:18090。

用法：
  H3_WORKBENCH_USER=admin H3_WORKBENCH_PASS=*** python h3_batch.py --batch x.jsonl --wait-all
  python h3_batch.py --dry-run --batch sample.jsonl   # 只打印将发起的 API 调用，不联网

依赖：Python 3.8+，requests（15 上 /opt/py312 已装）。--wait-all 的 ffprobe 校验
额外需要 ffprobe（默认 PATH 查找，可用 --ffprobe 覆盖）。
"""
import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

# ---------- 工作台契约常量（源自 /opt/data/h3-studio/server/app.py） ----------

DEFAULT_BASE = "http://127.0.0.1:18090"
SESSION_COOKIE = "h3_session"          # app.py:151（httponly, samesite=lax, TTL 7 天, app.py:152）
LOGIN_PATH = "/api/login"              # app.py:951  POST JSON {username,password}（LoginReq, app.py:923）
TASKS_PATH = "/api/tasks"              # app.py:1049 POST 提交 / app.py:1109 GET 列表（无单任务 GET）
VIDEO_PATH_FMT = "/api/tasks/{}/video"  # app.py:1122 FileResponse mp4
ME_PATH = "/api/me"                    # app.py:982

ALLOWED_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4"]   # app.py:44
ALLOWED_TASKS = ["t2va", "fl2va"]                         # app.py:45
ALLOWED_QUALITIES = ["turbo", "native"]                   # app.py:46（turbo=9步LoRA / native=50步, app.py:49）
MIN_DURATION, MAX_DURATION = 5, 15                        # app.py:43
MAX_IMAGE_DATA = 12_000_000                               # app.py:47 data URI 字符上限


def validate_base(base: str) -> None:
    """拒绝把批量客户端绕过工作台指向 H3 引擎或带凭据的 URL。"""
    try:
        parsed = urlsplit(base)
        port = parsed.port
    except ValueError as e:
        raise ValueError(f"工作台地址无效: {e}") from e
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("工作台地址必须是带主机名的 http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("工作台地址不得内嵌用户名或密码")
    if parsed.hostname.lower() not in {"127.0.0.1", "localhost"} or port != 18090:
        raise ValueError("工作台地址必须是本机回环 127.0.0.1:18090；其他机器请先做 SSH 端口转发")


STATUS_QUEUED = "queued"          # app.py:1104
STATUS_GENERATING = "generating"  # app.py:702
STATUS_DONE = "done"              # app.py:698/714
STATUS_FAILED = "failed"          # app.py:736

# 登录限流：按 IP 10 分钟内 5 次失败 → 429（app.py:929-930），
# 因此本脚本全程只登录一次，复用 cookie；仅在收到 401 时补登录一次。

# ---------- 日志（stdout 与 task log 均为一行一条 JSON） ----------

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def emit(obj: dict) -> None:
    """stdout 事件流：一行一条 JSON，便于机读。"""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def log_event(log_f, rec: dict) -> None:
    """task log（断点续跑依据）：一行一条 JSON，追加写。"""
    log_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log_f.flush()


# ---------- 工作台客户端 ----------

try:
    import requests
except ImportError:  # dry-run 不需要 requests
    requests = None


class WorkbenchError(RuntimeError):
    pass


class WorkbenchAuthError(WorkbenchError):
    pass


class Workbench:
    """Molispark 工作台 HTTP 客户端。密码只在内存中保存，绝不打印、不落日志。"""

    def __init__(self, base: str, user: str, password: str, dry_run: bool = False):
        self.base = base.rstrip("/")
        self.user = user
        self._password = password
        self.dry_run = dry_run
        self._session = None
        self._logged_in = False

    # ---- 底层请求：GET 等幂等请求异常指数退避；POST 不自动重试 ----

    def _request(self, method: str, path: str, *, relogin_on_401: bool = True, **kw):
        url = self.base + path
        delay = 2.0
        while True:
            try:
                r = self._session.request(method, url, timeout=kw.pop("timeout", (10, 60)), **kw)
            except Exception as e:  # requests.RequestException 等：工作台瞬时重启
                emit({"event": "http_error", "method": method, "path": path,
                      "error": type(e).__name__,
                      "retry_in_s": None if method.upper() == "POST" else delay})
                if method.upper() == "POST":
                    raise WorkbenchError(
                        f"POST {path} 请求失败，未自动重试以避免重复提交: {type(e).__name__}"
                    ) from e
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            if r.status_code == 401 and relogin_on_401 and self._logged_in:
                # cookie 过期/失效：补登录一次后重试原请求
                emit({"event": "relogin", "path": path})
                self._logged_in = False
                self.login()
                return self._request(method, path, relogin_on_401=False, **kw)
            if r.status_code >= 500:
                # 创建任务不是幂等操作；未知结果时不自动重试，避免重复扣额度。
                if method.upper() == "POST":
                    return r
                # GET 等幂等请求可在工作台瞬时重启时指数退避重试。
                emit({"event": "http_5xx", "method": method, "path": path,
                      "status_code": r.status_code, "retry_in_s": delay})
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue
            return r

    # ---- 登录：全程一次（限流红线：10 分钟 5 次失败/IP） ----

    def login(self) -> dict:
        if self.dry_run:
            return {"username": self.user or "<env 未设置>", "is_admin": None}
        if self._session is None:
            self._session = requests.Session()
        r = self._request("POST", LOGIN_PATH, relogin_on_401=False,
                          json={"username": self.user, "password": self._password})
        if r.status_code == 401:
            raise WorkbenchAuthError("登录失败：用户名或密码错误（注意 10 分钟 5 次失败会触发 429 限流）")
        if r.status_code == 429:
            raise WorkbenchAuthError("登录被限流（429）：该 IP 10 分钟内登录失败已达 5 次，请稍后再试")
        if r.status_code >= 400:
            raise WorkbenchError(f"登录失败 HTTP {r.status_code}: {r.text[:200]}")
        self._logged_in = True
        info = r.json()
        emit({"event": "login_ok", "username": info.get("username"),
              "is_admin": info.get("is_admin"), "cookie": SESSION_COOKIE})
        return info

    # ---- 业务端点 ----

    def submit(self, payload: dict) -> dict:
        r = self._request("POST", TASKS_PATH, json=payload)
        if r.status_code == 429:
            return {"_error": "quota_exhausted",
                    "detail": r.text[:200] or "今日额度已用完"}
        if r.status_code >= 400:
            return {"_error": "submit_failed", "status_code": r.status_code,
                    "detail": r.text[:300]}
        data = r.json()
        if not data.get("id"):
            return {"_error": "submit_failed", "detail": f"响应缺少 id: {data}"}
        return data  # {"id": <12hex>, "task_type": ...}

    def list_tasks(self) -> list:
        r = self._request("GET", TASKS_PATH)
        if r.status_code >= 400:
            raise WorkbenchError(f"GET {TASKS_PATH} HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def find_task(self, task_id: str):
        """无单任务 GET 端点（app.py 无该路由），列表里按 id 过滤。"""
        for t in self.list_tasks():
            if t.get("id") == task_id:
                return t
        return None

    def download(self, task_id: str, dest: Path) -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        r = self._request("GET", VIDEO_PATH_FMT.format(task_id), stream=True, timeout=(10, 120))
        if r.status_code >= 400:
            raise WorkbenchError(f"下载失败 HTTP {r.status_code}: {r.text[:200]}")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        size = tmp.stat().st_size
        if size < 1024:
            tmp.unlink(missing_ok=True)
            raise WorkbenchError(f"下载的视频异常（{size} 字节）")
        tmp.replace(dest)
        return size


# ---------- 批次行校验与 payload 构造 ----------

def load_batch(path: Path):
    """读 jsonl，返回 (lines, errors)。空行与 # 开头注释行跳过。"""
    lines, errors = [], []
    with open(path, encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append((i, f"JSON 解析失败: {e}"))
                continue
            if not isinstance(obj, dict):
                errors.append((i, "每行必须是 JSON 对象"))
                continue
            lines.append((i, obj))
    return lines, errors


def validate_line(obj: dict) -> list:
    errs = []
    for key in ("prompt", "task", "duration", "ar", "out"):
        if key not in obj:
            errs.append(f"缺少字段 {key}")
    if "prompt" in obj and not (isinstance(obj["prompt"], str) and obj["prompt"].strip()):
        errs.append("prompt 不能为空")
    if "prompt" in obj and len(obj["prompt"]) > 2000:
        errs.append("prompt 超过 2000 字符（app.py:909）")
    if obj.get("task") not in ALLOWED_TASKS:
        errs.append(f"task 只支持 {ALLOWED_TASKS}")
    dur = obj.get("duration")
    if not isinstance(dur, int) or not (MIN_DURATION <= dur <= MAX_DURATION):
        errs.append(f"duration 必须是 {MIN_DURATION}-{MAX_DURATION} 的整数秒（app.py:43）")
    if obj.get("ar") not in ALLOWED_RATIOS:
        errs.append(f"ar 只支持 {ALLOWED_RATIOS}（app.py:44）")
    if obj.get("quality", "turbo") not in ALLOWED_QUALITIES:
        errs.append(f"quality 只支持 {ALLOWED_QUALITIES}（app.py:46）")
    if not isinstance(obj.get("out", ""), str) or not obj.get("out"):
        errs.append("out 必须是非空字符串（15 上的输出绝对路径）")
    if obj.get("task") == "fl2va":
        img = obj.get("image")
        if not isinstance(img, str) or not img:
            errs.append("fl2va 必须提供 image（15 上参考图绝对路径，首帧）")
    return errs


def build_payload(obj: dict) -> tuple:
    """返回 (payload, image_note)。fl2va 参考图读盘 → base64 data URI（app.py:915/439）。"""
    payload = {
        "prompt": obj["prompt"].strip(),
        "duration": obj["duration"],
        "aspect_ratio": obj["ar"],
        "task_type": obj["task"],
        "quality": obj.get("quality", "turbo"),
    }
    if obj.get("seed") is not None:
        payload["seed"] = obj["seed"]
    note = None
    if obj["task"] == "fl2va":
        img_path = Path(obj["image"])
        if not img_path.exists():
            raise WorkbenchError(f"参考图不存在: {img_path}")
        mime, _ = mimetypes.guess_type(str(img_path))
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        data_uri = "data:{};base64,{}".format(
            mime, base64.b64encode(img_path.read_bytes()).decode())
        if len(data_uri) > MAX_IMAGE_DATA:
            raise WorkbenchError(f"参考图超过上限（data URI {len(data_uri)} > {MAX_IMAGE_DATA} 字符, app.py:47）")
        payload["image_data"] = data_uri
        note = {"image": str(img_path), "mime": mime,
                "bytes": img_path.stat().st_size, "data_uri_chars": len(data_uri)}
    return payload, note


# ---------- task log（断点续跑） ----------

def load_log_state(log_path: Path) -> dict:
    """读取 <batch>.log.jsonl，返回 {idx: 最后一条记录}。"""
    state = {}
    if not log_path.exists():
        return state
    with open(log_path, encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "idx" in rec:
                state[rec["idx"]] = rec
    return state


RESUME_STATUSES = {"submitted", "polling", "timeout"}  # 凭 workbench_task_id 重挂轮询


# ---------- 单条任务执行 ----------

def submit_and_wait(client, idx, line, args, log_f, existing_tid=None) -> str:
    """提交（或重挂）一条任务并阻塞到终态。返回终态: completed|failed|timeout。"""
    if existing_tid is None:
        payload, image_note = build_payload(line)
        emit({"event": "submit", "idx": idx, "out": line["out"],
              "task": line["task"], "duration": line["duration"], "ar": line["ar"],
              "image": image_note})
        if args.dry_run:
            emit({"event": "dry_run_call", "method": "POST", "path": TASKS_PATH,
                  "json": {k: (v[:48] + "…<data URI, 已截断>" if k == "image_data" else v)
                           for k, v in payload.items()}})
            tid = f"dry-run-{idx}"
            log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                              "workbench_task_id": tid, "status": "submitted",
                              "dry_run": True})
        else:
            res = client.submit(payload)
            if res.get("_error"):
                log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                                  "status": "failed", "reason": res["_error"],
                                  "detail": res.get("detail")})
                emit({"event": "submit_failed", "idx": idx, "reason": res["_error"],
                      "detail": res.get("detail")})
                return "failed"
            tid = res["id"]
            log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                              "workbench_task_id": tid, "status": "submitted"})
    else:
        tid = existing_tid
        emit({"event": "reattach", "idx": idx, "workbench_task_id": tid})

    if args.dry_run:
        emit({"event": "dry_run_call", "method": "GET", "path": TASKS_PATH,
              "note": f"每 {args.poll_interval}s 轮询直到 done/failed；"
                      f"自首次见到 generating 起 {args.timeout}s 硬超时（queued 不计）"})
        emit({"event": "dry_run_call", "method": "GET",
              "path": VIDEO_PATH_FMT.format(tid), "note": f"done 后流式下载落盘到 {line['out']}"})
        emit({"event": "dry_run_ok", "idx": idx, "note": "dry-run 不实际生成，标记完成"})
        log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                          "workbench_task_id": tid, "status": "completed", "dry_run": True})
        return "completed"

    # ---- 轮询直到终态 ----
    log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                      "workbench_task_id": tid, "status": "polling"})
    gen_since = None
    last_status = None
    while True:
        info = client.find_task(tid)
        if info is None:
            # 任务从列表消失（被删/库丢失）：只能重新提交
            emit({"event": "task_missing", "idx": idx, "workbench_task_id": tid,
                  "note": "列表中已不存在，将重新提交"})
            return submit_and_wait(client, idx, line, args, log_f, existing_tid=None)
        st = info.get("status")
        if st != last_status:
            emit({"event": "status", "idx": idx, "workbench_task_id": tid,
                  "status": st, "error_code": info.get("error_code"),
                  "error": (info.get("error") or "")[:200] or None})
            last_status = st
        if st == STATUS_QUEUED:
            pass  # 排队等待不计超时
        elif st == STATUS_GENERATING:
            if gen_since is None:
                gen_since = info.get("started") or time.time()
                emit({"event": "generating_since", "idx": idx, "workbench_task_id": tid,
                      "generating_since": gen_since})
            if time.time() - gen_since > args.timeout:
                reason = ("polling_timeout: 自任务进入 generating 起超过 "
                          f"{args.timeout}s（工作台任务 {tid} 保留，未删除，可凭 id 重挂）")
                log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                                  "workbench_task_id": tid, "status": "timeout",
                                  "reason": reason})
                emit({"event": "timeout", "idx": idx, "workbench_task_id": tid,
                      "timeout_s": args.timeout, "note": "继续下一条"})
                return "timeout"
        elif st == STATUS_DONE:
            out_path = Path(line["out"])
            size = client.download(tid, out_path)
            log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                              "workbench_task_id": tid, "status": "completed",
                              "bytes": size})
            emit({"event": "completed", "idx": idx, "workbench_task_id": tid,
                  "out": str(out_path), "bytes": size})
            return "completed"
        elif st == STATUS_FAILED:
            log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                              "workbench_task_id": tid, "status": "failed",
                              "error_code": info.get("error_code"),
                              "error": (info.get("error") or "")[:500]})
            emit({"event": "failed", "idx": idx, "workbench_task_id": tid,
                  "error_code": info.get("error_code"),
                  "error": (info.get("error") or "")[:200]})
            return "failed"
        else:
            emit({"event": "unknown_status", "idx": idx, "status": st,
                  "note": "未知状态，继续轮询"})
        time.sleep(args.poll_interval)


# ---------- --wait-all：ffprobe 校验 ----------

def ffprobe_check(ffprobe: str, path: Path, want_duration: int, want_ar: str) -> dict:
    """返回媒体信息并校验 H3 输出的时长、画幅、分辨率与 h264/aac 编码。"""
    result = {"ok": False, "duration_s": None, "resolution": None,
              "video_codec": None, "audio_codec": None, "has_audio": None,
              "problems": []}
    if not path.exists():
        result["problems"].append("输出文件不存在")
        return result
    try:
        p = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        result["problems"].append(f"ffprobe 不存在: {ffprobe}")
        return result
    except subprocess.TimeoutExpired:
        result["problems"].append("ffprobe 超时")
        return result
    if p.returncode != 0:
        result["problems"].append(f"ffprobe 失败: {p.stderr.strip()[:200]}")
        return result
    data = json.loads(p.stdout or "{}")
    dur = data.get("format", {}).get("duration")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    result["has_audio"] = a is not None
    result["video_codec"] = v.get("codec_name") if v else None
    result["audio_codec"] = a.get("codec_name") if a else None
    if dur is not None:
        result["duration_s"] = round(float(dur), 2)
        if abs(float(dur) - want_duration) > 1.5:
            result["problems"].append(f"时长偏差过大: 实际 {float(dur):.2f}s ≠ 请求 {want_duration}s")
    else:
        result["problems"].append("ffprobe 未返回时长")
    if v and v.get("width") and v.get("height"):
        w, h = int(v["width"]), int(v["height"])
        result["resolution"] = f"{w}x{h}"
        try:
            ww, hh = (float(x) for x in want_ar.split(":"))
            if abs((w / h) / (ww / hh) - 1.0) > 0.02:
                result["problems"].append(f"画幅不符: {w}x{h} ≠ {want_ar}")
            if want_ar == "16:9" and (w, h) != (1344, 768):
                result["problems"].append(f"16:9 输出应为 1344x768，实际 {w}x{h}")
        except (ValueError, ZeroDivisionError):
            pass
    else:
        result["problems"].append("无视频流")
    if not result["has_audio"]:
        result["problems"].append("无音轨")
    if result["video_codec"] != "h264":
        result["problems"].append(f"视频编码应为 h264，实际 {result['video_codec'] or '未知'}")
    if result["audio_codec"] != "aac":
        result["problems"].append(f"音频编码应为 aac，实际 {result['audio_codec'] or '未知'}")
    result["ok"] = not result["problems"]
    return result


# ---------- 主流程 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="Molispark Design 工作台批量视频脚本（禁直连 18081）")
    ap.add_argument("--batch", required=True, help="批次 jsonl 路径（一行一片）")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help=f"工作台地址（仅允许 127.0.0.1:18090，默认 {DEFAULT_BASE}）")
    ap.add_argument("--ffprobe", default="ffprobe", help="ffprobe 路径（默认 PATH 查找）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将发起的 API 调用与 payload，不联网不生成")
    ap.add_argument("--wait-all", action="store_true",
                    help="全部终态后逐条 ffprobe 校验（时长/画幅/1344x768/h264/aac）并打印汇总表，有失败以非零码退出")
    ap.add_argument("--retry-failed", action="store_true",
                    help="对 log 中 failed 的条目重新提交（默认跳过）")
    ap.add_argument("--poll-interval", type=int, default=10, help="轮询间隔秒数（默认 10）")
    ap.add_argument("--timeout", type=int, default=15 * 60,
                    help="单条硬超时秒数，自 generating 起算（默认 900；queued 不计）")
    ap.add_argument("--log", default=None, help="task log 路径（默认 <batch>.log.jsonl）")
    args = ap.parse_args()

    try:
        validate_base(args.base)
    except ValueError as e:
        emit({"event": "fatal", "error": str(e)})
        return 2

    batch_path = Path(args.batch)
    if not batch_path.exists():
        emit({"event": "fatal", "error": f"批次文件不存在: {batch_path}"})
        return 2
    log_path = Path(args.log) if args.log else batch_path.with_suffix(batch_path.suffix + ".log.jsonl")

    lines, load_errs = load_batch(batch_path)
    if load_errs:
        for i, e in load_errs:
            emit({"event": "batch_error", "line": i, "error": e})
        emit({"event": "fatal", "error": f"{len(load_errs)} 行输入无效，未执行任何任务"})
        return 2
    if not lines:
        emit({"event": "fatal", "error": "批次中没有有效行"})
        return 2

    # 校验每一行
    valid, invalid = [], []
    for i, obj in lines:
        errs = validate_line(obj)
        if errs:
            invalid.append(i)
            emit({"event": "batch_error", "line": i, "errors": errs})
        else:
            valid.append((i, obj))
    if invalid:
        emit({"event": "fatal", "error": f"{len(invalid)} 行校验失败，未执行任何任务"})
        return 2

    # 凭据：仅从环境变量读；绝不打印密码
    user = os.environ.get("H3_WORKBENCH_USER")
    password = os.environ.get("H3_WORKBENCH_PASS")
    if not args.dry_run and (not user or not password):
        emit({"event": "fatal", "error": "缺少凭据：请设置环境变量 H3_WORKBENCH_USER / H3_WORKBENCH_PASS"})
        return 2
    if not args.dry_run and requests is None:
        emit({"event": "fatal", "error": "缺少依赖 requests（pip install requests）"})
        return 2
    if args.dry_run:
        emit({"event": "dry_run_start", "batch": str(batch_path), "base": args.base,
              "cred_user_set": bool(user), "cred_pass_set": bool(password),
              "items": len(valid),
              "note": "不会登录、不会提交、不会生成；密码不出现在任何输出中"})

    state = load_log_state(log_path)
    client = Workbench(args.base, user or "", password or "", dry_run=args.dry_run)

    try:
        if not args.dry_run:
            client.login()
            me = client._request("GET", ME_PATH).json()
            emit({"event": "quota", "username": me.get("username"),
                  "daily_limit": me.get("daily_limit"), "used": me.get("used"),
                  "remaining": me.get("remaining")})
    except WorkbenchError as e:
        emit({"event": "fatal", "error": str(e)})
        return 3

    def dispatch(idx, line, log_f) -> str:
        """单条分派：按 log 状态决定跳过/重挂/重提；本地错误（如参考图缺失）记为 failed。"""
        out = line["out"]
        prev = state.get(idx)
        try:
            if prev and prev.get("status") == "completed" and Path(out).exists():
                emit({"event": "skip", "idx": idx, "reason": "log 已 completed 且产物存在",
                      "workbench_task_id": prev.get("workbench_task_id")})
                return "completed"
            if prev and prev.get("status") == "completed" and not Path(out).exists():
                # 产物丢失：若任务还在保留期（14 天）内，重挂下载
                return submit_and_wait(client, idx, line, args, log_f,
                                       existing_tid=prev.get("workbench_task_id"))
            if prev and prev.get("status") == "failed":
                if args.retry_failed:
                    emit({"event": "retry_failed", "idx": idx,
                          "workbench_task_id": prev.get("workbench_task_id")})
                    return submit_and_wait(client, idx, line, args, log_f)
                emit({"event": "skip", "idx": idx, "reason": "log 为 failed（加 --retry-failed 重提）",
                      "workbench_task_id": prev.get("workbench_task_id")})
                return "failed"
            if prev and prev.get("status") in RESUME_STATUSES and prev.get("workbench_task_id"):
                return submit_and_wait(client, idx, line, args, log_f,
                                       existing_tid=prev["workbench_task_id"])
            return submit_and_wait(client, idx, line, args, log_f)
        except WorkbenchError as e:
            # 本地可预判错误（参考图不存在/超大等）：不提交、不扣额度，记 failed 继续下一条
            log_event(log_f, {"ts": now_iso(), "idx": idx, "out": line["out"],
                              "status": "failed", "reason": "local_error", "error": str(e)[:500]})
            emit({"event": "item_error", "idx": idx, "error": str(e)})
            return "failed"

    results = {}  # idx -> 终态字符串
    with open(log_path, "a", encoding="utf-8") as log_f:
        for idx, line in valid:
            results[idx] = dispatch(idx, line, log_f)

    # ---- --wait-all：终态校验汇总 ----
    if args.wait_all:
        emit({"event": "wait_all_start"})
        rows, fail_count = [], 0
        for idx, line in valid:
            st = results.get(idx, "unknown")
            if st == "completed":
                chk = ffprobe_check(args.ffprobe, Path(line["out"]),
                                    line["duration"], line["ar"])
                rows.append((idx, st, str(line["out"]),
                             chk["duration_s"], chk["resolution"], chk["has_audio"],
                             "; ".join(chk["problems"]) or "OK"))
                if not chk["ok"]:
                    fail_count += 1
            else:
                rows.append((idx, st, str(line["out"]), "-", "-", "-", "非 completed，未校验"))
                fail_count += 1
        emit({"event": "summary",
              "table": [{"idx": r[0], "status": r[1], "out": r[2], "duration_s": r[3],
                         "resolution": r[4], "has_audio": r[5], "check": r[6]} for r in rows],
              "total": len(rows), "failed": fail_count})
        # 人类可读汇总表
        print("\n===== wait-all 汇总 =====", flush=True)
        print(f"{'idx':>4} {'status':<10} {'duration':>9} {'resolution':<12} {'audio':<6} check / out",
              flush=True)
        for r in rows:
            print(f"{r[0]:>4} {r[1]:<10} {str(r[3] if r[3] is not None else '-'):>9} "
                  f"{str(r[4] if r[4] is not None else '-'):<12} "
                  f"{str(r[5] if r[5] is not None else '-'):<6} {r[6]}  {r[2]}",
                  flush=True)
        print(f"合计 {len(rows)} 条，失败 {fail_count} 条", flush=True)
        if fail_count:
            emit({"event": "wait_all_failed", "failed": fail_count})
            return 1

    bad = sum(1 for s in results.values() if s != "completed")
    if bad:
        emit({"event": "done_with_errors", "failed_items": bad, "total": len(results)})
        return 1
    emit({"event": "done", "total": len(results)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
