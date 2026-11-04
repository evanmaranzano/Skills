#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jszx 服务器 SSH 助手（任意 11-17），凭据从权威文档运行时读入，不回显不落盘。
用法: from jszx_ssh import run;  run('10.10.127.17', 'docker ps')"""
import sys
from pathlib import Path
import paramiko

sys.path.insert(0, "/home/dev/.agents/skills/video-workflow/scripts")
from om_ssh import _cred_file


def _pwd(host: str) -> str:
    with open(_cred_file(), encoding="utf-8") as f:
        for line in f:
            if host in line and "`root`" in line and "/" in line:
                for part in (p.strip() for p in line.split("|")):
                    if part.startswith("`root`") and "/" in part:
                        return part.split("/", 1)[1].strip().strip("`").strip()
    # 备用：独立“服务器 SSH”小节中的 host 行
    with open(_cred_file(), encoding="utf-8") as f:
        txt = f.read()
    import re
    m = re.search(re.escape(host) + r"[^\n]{0,80}?root\s*/\s*`?([^\s|`]+)", txt)
    if m:
        return m.group(1)
    raise RuntimeError(f"root credential for {host} not found")


def run(host: str, cmd: str, timeout: int = 900):
    c = paramiko.SSHClient()
    c.load_system_host_keys()
    known = Path.home() / ".ssh" / "known_hosts"
    if known.exists():
        c.load_host_keys(str(known))
    c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(host, port=22, username="root", password=_pwd(host),
              timeout=15, allow_agent=False, look_for_keys=False)
    try:
        _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
        code = stdout.channel.recv_exit_status()
        return code, stdout.read().decode("utf-8", "replace"), stderr.read().decode("utf-8", "replace")
    finally:
        c.close()
