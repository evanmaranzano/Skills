#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""远程渲染驱动（通用版）：上传素材 → 15 后台渲染 → 轮询 → 拉回成片。

依赖同目录的 `om_ssh.py`。用法：
  python render_remote.py --project <name> --composition <CompId> \
      --local-public ./public --local-index ./index.tsx \
      [--duration-s 180] [--concurrency 6] [--gl angle] [--scale 0.5] \
      [--clean-remote] [--wait] [--wait-timeout-s 1800] [--out ./final.mp4]

--scale 0.5 = 探针渲染（960x540，速度快约 4-6 倍），用于终渲前的全场景 QA。

从 skill 自带 scripts/om_ssh.py 导入 SSH 助手。
远端布局：/opt/data/om-deploy/OpenMontage/
  remotion-composer/projects/<project>/index.tsx
  projects/<project>/public/...
  projects/<project>/renders/final.mp4
"""
import argparse
import re
import sys
import time
from pathlib import Path

# 导入 skill 自带的 om_ssh
SCRIPT_DIR = Path(__file__).resolve().parent
if not (SCRIPT_DIR / "om_ssh.py").exists():
    sys.exit(f"skill 内缺少 om_ssh.py：{SCRIPT_DIR}")
sys.path.insert(0, str(SCRIPT_DIR))
try:
    import om_ssh  # noqa
except Exception as e:
    sys.exit(f"无法导入 skill 自带 om_ssh.py：{e}")

REMOTE_ROOT = "/opt/data/om-deploy/OpenMontage"
REMOTE_COMPOSER = f"{REMOTE_ROOT}/remotion-composer"
CHROME = "/root/.cache/ms-playwright/chromium-1234/chrome-linux/chrome"
SAFE_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_slug(value: str, label: str) -> None:
    if not SAFE_SLUG.fullmatch(value):
        raise ValueError(f"{label} 只能包含字母、数字、点、下划线和连字符，且不能以特殊字符开头")


def remote_paths(project):
    atelier = f"{REMOTE_COMPOSER}/projects/{project}/index.tsx"
    pub = f"{REMOTE_ROOT}/projects/{project}/public"
    out = f"{REMOTE_ROOT}/projects/{project}/renders/final.mp4"
    return atelier, pub, out


def run(cmd, timeout=900):
    code, out, err = om_ssh.run(cmd, timeout=timeout)
    if code != 0:
        print(f"ERR ({code}): {err[:500]}", file=sys.stderr)
    return code, out, err


def upload_dir(local, remote, glob_pat):
    """上传 local 下匹配 glob_pat 的文件到 remote（扁平）。"""
    import glob
    files = sorted(Path(local).glob(glob_pat))
    if not files:
        print(f"  (no files match {glob_pat} in {local})")
        return 0
    code, _, err = om_ssh.run(f"mkdir -p {remote}")
    if code != 0:
        raise RuntimeError(f"创建远端目录失败 {remote}: {err[:300]}")
    for f in files:
        if f.is_file():
            om_ssh.put(str(f), f"{remote}/{f.name}")
            print(f"  put {f.name} ({f.stat().st_size//1024} KB)")
    return len(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--composition", required=True)
    ap.add_argument("--local-public", required=True, help="本机 public/ 目录")
    ap.add_argument("--local-index", required=True, help="本机 index.tsx")
    ap.add_argument("--duration-s", type=int, default=64)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--gl", default="angle", choices=["angle", "egl", "swiftshader"])
    ap.add_argument("--scale", type=float, default=1.0,
                    help="渲染缩放（0.5=探针 960x540 QA 用；1.0=正式 1080p）")
    ap.add_argument("--clean-remote", action="store_true",
                    help="删除该 project 的旧素材目录后再上传（仅清理已知 public 子目录）")
    ap.add_argument("--wait", action="store_true", help="轮询到完成并拉回")
    ap.add_argument("--wait-timeout-s", type=int, default=None,
                    help="--wait 总等待上限秒数（默认 max(900, duration-s×10)）")
    ap.add_argument("--out", default=None, help="成片拉回的本机路径")
    args = ap.parse_args()

    try:
        validate_slug(args.project, "project")
        validate_slug(args.composition, "composition")
    except ValueError as e:
        ap.error(str(e))
    if args.duration_s <= 0:
        ap.error("duration-s 必须为正数")
    if args.concurrency <= 0:
        ap.error("concurrency 必须为正整数")
    if not (0.1 <= args.scale <= 2.0):
        ap.error("scale 取值 0.1~2.0（探针用 0.5）")
    if args.wait_timeout_s is not None and args.wait_timeout_s <= 0:
        ap.error("wait-timeout-s 必须为正整数")
    local_public = Path(args.local_public)
    local_index = Path(args.local_index)
    if not local_public.is_dir():
        ap.error(f"local-public 目录不存在: {local_public}")
    if not local_index.is_file():
        ap.error(f"local-index 文件不存在: {local_index}")

    atelier, pub, out = remote_paths(args.project)
    log = f"/tmp/om_{args.project}_render.log"
    asset_dirs = [
        f"{pub}/assets/video",
        f"{pub}/assets/audio/narration",
        f"{pub}/assets/audio/bgm",
        f"{pub}/assets/audio/sfx",
        f"{pub}/fonts",
    ]

    print("=== 备份远端 index.tsx ===")
    ts = time.strftime("%Y%m%d-%H%M%S")
    code, _, err = run(
        f"mkdir -p {REMOTE_ROOT}/projects/{args.project}/renders; "
        f"if [ -f {atelier} ]; then cp {atelier} {atelier}.bak-{ts}; fi"
    )
    if code != 0:
        raise SystemExit(f"备份远端 index.tsx 失败: {err[:300]}")
    if args.clean_remote:
        print("=== 清理该 project 的旧素材目录 ===")
        code, _, err = run("rm -rf " + " ".join(asset_dirs))
        if code != 0:
            raise SystemExit(f"清理远端素材失败: {err[:300]}")

    print("=== 上传 index.tsx ===")
    code, _, err = run(f"mkdir -p $(dirname {atelier})")
    if code != 0:
        raise SystemExit(f"创建远端 atelier 目录失败: {err[:300]}")
    om_ssh.put(str(local_index), atelier)
    print(f"  put index.tsx ({local_index.stat().st_size//1024} KB)")

    print("=== 上传素材（video / narration / bgm / sfx / fonts）===")
    lp = local_public
    upload_dir(lp / "assets/video", f"{pub}/assets/video", "*.mp4")
    upload_dir(lp / "assets/audio/narration", f"{pub}/assets/audio/narration", "*.wav")
    upload_dir(lp / "assets/audio/bgm", f"{pub}/assets/audio/bgm", "*")
    upload_dir(lp / "assets/audio/sfx", f"{pub}/assets/audio/sfx", "*")
    upload_dir(lp / "fonts", f"{pub}/fonts", "*")

    print("=== 启动远程渲染（后台）===")
    scale_flag = f" --scale={args.scale}" if args.scale != 1.0 else ""
    render_cmd = (
        f"cd {REMOTE_COMPOSER} && "
        f"setsid bash -c 'echo START_TS=$(date +%s); "
        f"/usr/bin/time -f \"WALL %e\" npx remotion render "
        f"projects/{args.project}/index.tsx {args.composition} {out} "
        f"--public-dir={pub} --browser-executable={CHROME} "
        f"--concurrency={args.concurrency} --gl={args.gl} --crf=18 --timeout=60000{scale_flag}; "
        f"echo EXIT_CODE=$?' > {log} 2>&1 < /dev/null & echo LAUNCHED"
    )
    # setsid 后台命令可能让 SSH 通道短暂超时；超时时用远端日志确认是否已启动。
    try:
        launch_code, launch_out, launch_err = om_ssh.run(render_cmd, timeout=20)
    except Exception as e:
        check_code, check_out, check_err = om_ssh.run(
            f"test -f {log} && echo LOG_READY || true", timeout=30)
        if check_code != 0 or "LOG_READY" not in check_out:
            raise SystemExit(f"远端渲染启动失败且无法确认日志: {type(e).__name__}: {e}")
        print(f"启动通道超时，但远端日志已创建，继续轮询: {log}")
    else:
        if launch_code != 0 or "LAUNCHED" not in launch_out:
            raise SystemExit(f"远端渲染启动失败: {launch_err[:300] or launch_out[:300]}")
    print(f"渲染已启动，日志 {log}")

    if not args.wait:
        print(f"渲染已在远端后台启动，可通过 SSH 查看 {log}。--wait 必须在首次启动时指定；不要重跑整条命令，否则会重复提交。")
        return

    print("=== 轮询渲染 ===")
    wait_timeout = args.wait_timeout_s if args.wait_timeout_s is not None else max(900, args.duration_s * 10)
    deadline = time.monotonic() + wait_timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit(f"远端渲染等待超时（{wait_timeout}s），日志保留在 {log}")
        time.sleep(min(30, remaining))
        code, o, _ = run(
            f"if [ -f {log} ]; then tail -3 {log}; else echo LOG_MISSING; fi; echo '---'; "
            f"grep -c Rendered {log} 2>/dev/null || true; "
            f"grep EXIT_CODE {log} 2>/dev/null || true", timeout=30)
        if code != 0:
            print("⚠️ 读取远端渲染状态失败，继续等待", file=sys.stderr)
            continue
        print(o.strip().split("---")[0][-200:])
        if "LOG_MISSING" in o:
            raise SystemExit(f"远端渲染日志不存在: {log}")
        if "EXIT_CODE=0" in o:
            code, ready, err = run(f"test -s {out} && echo OUTPUT_READY || true", timeout=30)
            if code != 0 or "OUTPUT_READY" not in ready:
                raise SystemExit(f"渲染报告成功但成片文件不存在或为空: {err[:300]}")
            print("✅ 渲染完成")
            break
        if "EXIT_CODE=" in o:
            print(f"❌ 渲染失败：{o[-500:]}")
            sys.exit(1)

    if args.out:
        print(f"=== 拉回成片 -> {args.out} ===")
        local_out = Path(args.out)
        local_out.parent.mkdir(parents=True, exist_ok=True)
        om_ssh.get(out, str(local_out))
        size = local_out.stat().st_size
        if size < 1024:
            raise SystemExit(f"拉回的成片异常：{size} 字节")
        print(f"size: {size/1048576:.1f} MB")


if __name__ == "__main__":
    main()
