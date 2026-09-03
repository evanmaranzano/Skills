#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""15 服务器 SSH 助手（用户已显式授权本次部署使用）。
密码从桌面凭据文件运行时读入：不回显、不落盘、不写入任何日志。
用法：
  from om_ssh import run, run_env, put, get, workbench_admin
  code, out, err = run("node --version")
  put("C:/local/file", "/remote/file")
"""
import sys
from pathlib import Path

import paramiko

HOST = "10.10.127.15"
PORT = 22
USER = "root"


def _cred_file() -> str:
    """桌面「服务器信息整理<日期>.md」取文件名日期最新的一版（任意用户名可用）。"""
    import glob
    desktop = Path.home() / "Desktop"
    candidates = sorted(glob.glob(str(desktop / "服务器信息整理*.md")))
    if not candidates:
        raise RuntimeError(f"桌面未找到 服务器信息整理*.md（{desktop}）")
    return candidates[-1]


def _root_pwd() -> str:
    with open(_cred_file(), encoding="utf-8") as f:
        for line in f:
            if "10.10.127.15" in line and "`root`" in line and "/" in line:
                for part in (p.strip() for p in line.split("|")):
                    if part.startswith("`root`") and "/" in part:
                        return part.split("/", 1)[1].strip().strip("`").strip()
    raise RuntimeError("root credential for 10.10.127.15 not found")


def workbench_admin() -> tuple[str, str]:
    """从凭据文件读工作台 admin 账号/密码（运行时读入，不回显）。"""
    with open(_cred_file(), encoding="utf-8") as f:
        content = f.read()
    import re
    m = re.search(r"admin 密码 \d{4}-\d{2}-\d{2} 已重置\*\*[：:]\s*`?([0-9A-Za-z]+)`?", content)
    if not m:
        raise RuntimeError("workbench admin password not found")
    return ("admin", m.group(1))


def client() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.load_system_host_keys()
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if known_hosts.exists():
        c.load_host_keys(str(known_hosts))
    c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(HOST, port=PORT, username=USER, password=_root_pwd(),
              timeout=15, allow_agent=False, look_for_keys=False)
    return c


def run(cmd: str, timeout: int = 900) -> tuple[int, str, str]:
    c = client()
    try:
        _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        return code, out, err
    finally:
        c.close()


def run_env(cmd: str, env: dict, timeout: int = 1800) -> tuple[int, str, str]:
    """运行命令并注入环境变量：经 SSH stdin 通道逐行传输 NAME=VALUE，
    远端 shell export 后 exec 命令。凭据**不落盘、不进远端进程 cmdline**
    （/proc/<pid>/environ 仅 root 可读）。用于 h3_batch 等需凭据的脚本。
    """
    c = client()
    try:
        wrapper = 'while IFS= read -r __l; do export "$__l"; done; ' + cmd
        stdin, stdout, stderr = c.exec_command(wrapper, timeout=timeout)
        for k, v in env.items():
            stdin.write(f"{k}={v}\n")
        stdin.flush()
        stdin.channel.shutdown_write()
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        return code, out, err
    finally:
        c.close()


def put(local: str, remote: str) -> None:
    c = client()
    try:
        sftp = c.open_sftp()
        sftp.put(local, remote)
        sftp.close()
    finally:
        c.close()


def get(remote: str, local: str) -> None:
    c = client()
    try:
        sftp = c.open_sftp()
        sftp.get(remote, local)
        sftp.close()
    finally:
        c.close()


if __name__ == "__main__":
    # 自检：只读命令
    code, out, _ = run("hostname; uptime")
    print(out)
    sys.exit(code)
