"""Shared formatting for WeChat API errors and credential-safe diagnostics."""

import ipaddress
import re

import requests


_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&](?:access_token|app_secret|secret)=)[^&\s]+"
)
_IP_TOKEN = re.compile(r"[0-9A-Fa-f:.]+")


def redact_sensitive_text(value):
    """Redact credentials that may appear in a request URL or error string."""
    return _SENSITIVE_QUERY_VALUE.sub(r"\1<redacted>", str(value))


def _extract_ips(text):
    ips = []
    for token in _IP_TOKEN.findall(text):
        candidate = token.strip(".,;()[]{}<>\"'")
        if "." not in candidate and ":" not in candidate:
            continue
        try:
            address = str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
        if address not in ips:
            ips.append(address)
    return ips


def _query_public_ip():
    """Resolve the current outbound IP only when WeChat omits it from 40164."""
    try:
        response = requests.get("https://api.ipify.org", timeout=5)
        response.raise_for_status()
        return str(ipaddress.ip_address(response.text.strip()))
    except Exception:
        return None


def format_wechat_api_error(errcode, errmsg):
    safe_errmsg = redact_sensitive_text(errmsg or "未知错误")
    try:
        code = int(errcode)
    except (TypeError, ValueError):
        code = errcode

    if code != 40164:
        return f"微信接口错误[{code}]: {safe_errmsg}"

    ips = _extract_ips(safe_errmsg)
    source = "微信错误返回的来源 IP"
    if not ips:
        public_ip = _query_public_ip()
        if public_ip:
            ips = [public_ip]
            source = "当前网络查询到的公网出口 IP"

    lines = ["微信公众号接口返回 40164：当前请求出口 IP 不在公众号 IP 白名单中。"]
    if ips:
        lines.append(f"{source}: {', '.join(ips)}")
    else:
        lines.append("未能自动识别公网出口 IP，请在发起请求的同一网络/代理环境中查询。")

    if safe_errmsg:
        lines.append(f"微信返回：{safe_errmsg}")

    lines.append(
        "配置方法：登录 mp.weixin.qq.com → 设置与开发 → 基本配置 → IP 白名单，"
        "添加上面的公网出口 IP 并保存，然后重试。"
    )
    lines.append(
        "若通过 VPN、代理或云主机访问，白名单应填写微信实际看到的出口 IP；"
        "优先采用微信错误返回的来源 IP。"
    )
    return "\n".join(lines)
