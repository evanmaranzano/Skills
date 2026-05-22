#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat_hot_article.py — 微信24h热文榜抓取 + 垂类评分 + 飞书文档发布

纯 Python 标准库，无需 pip install。
如果系统有 curl/scrapling/lark-cli 则自动升级使用。

Usage:
  python wechat_hot_article.py fetch   [--url URL] [--out PATH] [--css CSS]
  python wechat_hot_article.py rank    [--items PATH] [--vertical VERT] [--top N] [--out PATH]
  python wechat_hot_article.py search  --query QUERY [--out PATH]
  python wechat_hot_article.py publish [--content PATH] [--title TITLE] [--public] [--out PATH]
  python wechat_hot_article.py full    [--url URL] [--vertical VERT] [--top N] [--out PATH]
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOPHUB_WECHAT_URL = "https://tophub.today/n/WnBe01o371"

VERTICAL_KEYWORDS: Dict[str, List[str]] = {
    "AI": [
        "AI", "人工智能", "大模型", "DeepSeek", "OpenAI", "Claude", "Gemini",
        "GPT", "LLM", "Agent", "智能体", "AIGC", "生成式", "Copilot",
        "Sora", "Midjourney", "Stable Diffusion", "transformer",
        "深度学习", "机器学习", "神经网络", "AGI", "多模态",
        "Anthropic", "Google AI", "Meta AI", "微软", "芯片", "GPU",
        "NVIDIA", "英伟达", "算力", "RAG", "微调", "推理",
    ],
    "科技": [
        "AI", "人工智能", "大模型", "DeepSeek", "OpenAI", "Claude", "Gemini",
        "字节", "腾讯", "阿里", "百度", "华为", "小米", "苹果", "英伟达",
        "芯片", "机器人", "自动驾驶", "Agent", "智能体", "SaaS", "开源",
        "程序员", "产品经理", "创业", "科技", "数码", "互联网", "模型",
        "GPT", "LLM", "transformer", "深度学习", "机器学习", "GPU",
    ],
    "财经": [
        "股票", "基金", "A股", "港股", "美股", "利率", "通胀", "GDP",
        "央行", "降息", "加息", "经济", "金融", "投资", "理财", "楼市",
        "房价", "比特币", "加密货币", "银行", "保险",
    ],
    "教育": [
        "高考", "考研", "大学", "教育", "培训", "课程", "学科", "辅导",
        "招生", "毕业", "就业", "校园", "学生", "教师", "双减",
    ],
    "健康": [
        "医疗", "健康", "医院", "医生", "药物", "疫苗", "疾病", "体检",
        "养生", "中医", "手术", "癌症", "心理健康", "饮食",
    ],
    "消费": [
        "消费", "购物", "电商", "品牌", "直播", "带货", "美妆", "食品",
        "汽车", "新能源", "特斯拉", "比亚迪", "餐饮", "旅游",
    ],
    "职场": [
        "职场", "公司", "管理", "裁员", "招聘", "薪资", "加班", "996",
        "跳槽", "面试", "简历", "内卷", "打工人",
    ],
    "娱乐": [
        "电影", "综艺", "明星", "音乐", "游戏", "动漫", "影视", "演员",
        "导演", "票房", "热搜", "八卦", "网红",
    ],
}

NOISE_KEYWORDS = {
    "今日热榜", "登录", "注册", "关于", "隐私", "用户协议", "App Store",
    "Github", "API", "PRO", "更多", "反馈", "首页", "扫码", "下载App",
}

# ---------------------------------------------------------------------------
# HTML Parsing
# ---------------------------------------------------------------------------

def extract_items_from_html(raw_html: str) -> List[Dict]:
    """Extract leaderboard items from TopHub page (HTML or Markdown from Scrapling).

    HTML structure: <tr><td>rank.</td><td><a href="url">title</a></td><td class="ws">hot</td></tr>
    Markdown table: | rank. | [title](url) | hot | ...
    """
    items: List[Dict] = []
    seen: set = set()

    # Strategy 1: Markdown table from Scrapling (e.g. | 1. | [title](url) | hot |)
    for m in re.finditer(
        r"\|\s*(\d+)\.\s*\|\s*\[([^\]]+)\]\((https?://[^\s\)]+)\)\s*\|\s*([\d.万]+)",
        raw_html,
    ):
        rank = int(m.group(1))
        title = m.group(2).strip()
        url = m.group(3).strip()
        hot = m.group(4).strip()
        if title in seen or len(title) < 4:
            continue
        seen.add(title)
        items.append({"rank": rank, "title": title, "url": url, "hot": hot})

    if items:
        return items[:50]

    # Strategy 2: Markdown table without hot value (e.g. | 1. | [title](url) |)
    for m in re.finditer(
        r"\|\s*(\d+)\.\s*\|\s*\[([^\]]+)\]\((https?://[^\s\)]+)\)\s*\|",
        raw_html,
    ):
        rank = int(m.group(1))
        title = m.group(2).strip()
        url = m.group(3).strip()
        if title in seen or len(title) < 4:
            continue
        seen.add(title)
        items.append({"rank": rank, "title": title, "url": url, "hot": ""})

    if items:
        return items[:50]

    # Strategy 3: HTML <tr> blocks
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", raw_html, re.DOTALL)
    if trs:
        for tr in trs:
            rank_m = re.search(r"<td[^>]*>\s*(\d+)\.\s*</td>", tr)
            if not rank_m:
                continue
            rank = int(rank_m.group(1))

            a_m = re.search(
                r'<td>\s*<a\s+href="([^"]+)"[^>]*>([^<]+)</a>',
                tr,
            )
            if not a_m:
                continue
            url = a_m.group(1).strip()
            title = html.unescape(re.sub(r"\s+", " ", a_m.group(2).strip()))

            if title in seen or len(title) < 4:
                continue

            hot_m = re.search(r'<td\s+class="ws"[^>]*>\s*([^<]+)\s*</td>', tr)
            hot = hot_m.group(1).strip() if hot_m else ""

            seen.add(title)
            items.append({"rank": rank, "title": title, "url": url, "hot": hot})

    if items:
        return items[:50]

    # Strategy 4: Fallback - find all <a> with mp.weixin.qq.com hrefs
    for m in re.finditer(
        r'<a\s+href="(https://mp\.weixin\.qq\.com/[^"]*)"[^>]*>([^<]+)</a>',
        raw_html,
    ):
        url = m.group(1)
        title = html.unescape(re.sub(r"\s+", " ", m.group(2).strip()))
        if title in seen or len(title) < 4:
            continue
        seen.add(title)
        items.append({"rank": len(items) + 1, "title": title, "url": url, "hot": ""})

    return items[:50]


# ---------------------------------------------------------------------------
# Bootstrap: auto-install lightweight anti-bot dependency
# ---------------------------------------------------------------------------

def ensure_curl_cffi():
    """Try to import curl_cffi; if missing, auto-install via pip."""
    try:
        import curl_cffi
        return curl_cffi
    except ImportError:
        pass

    print("[bootstrap] curl_cffi not found, installing...", file=sys.stderr)
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "curl_cffi", "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        import curl_cffi
        return curl_cffi
    except Exception as e:
        print(f"[bootstrap] curl_cffi install failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Fetch Strategies
# ---------------------------------------------------------------------------

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.6422.113 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}


def fetch_curl_cffi(url: str, timeout: int = 20, retries: int = 3) -> str:
    curl_cffi = ensure_curl_cffi()
    if not curl_cffi:
        raise RuntimeError("curl_cffi not available and auto-install failed")

    from curl_cffi import requests as cffi_requests

    last_error = None
    for i in range(retries):
        try:
            resp = cffi_requests.get(
                url,
                headers=BROWSER_HEADERS,
                timeout=timeout,
                impersonate="chrome",
            )
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_error = str(e)
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"curl_cffi failed after {retries} retries: {last_error}")


def fetch_urllib(url: str, timeout: int = 20, retries: int = 3) -> str:
    import gzip
    last_error = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                # Handle gzip even though we don't request it (some CDNs ignore)
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body.decode("utf-8", errors="replace")
        except Exception as e:
            last_error = str(e)
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"urllib failed after {retries} retries: {last_error}")


def fetch_curl(url: str, timeout: int = 30) -> str:
    if not shutil.which("curl"):
        raise RuntimeError("curl not available")
    headers_list = []
    for k, v in BROWSER_HEADERS.items():
        headers_list.extend(["-H", f"{k}: {v}"])
    cmd = ["curl", "-sL", "--compressed", "--max-time", str(timeout)] + headers_list + [url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(f"curl exit {result.returncode}: {result.stderr[:200]}")
    return result.stdout


def fetch_scrapling(url: str, timeout: int = 30) -> str:
    scrapling_bin = shutil.which("scrapling")
    if not scrapling_bin:
        raise RuntimeError("scrapling not available")
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w") as tmp:
        tmp_path = tmp.name

    strategies = [
        [scrapling_bin, "extract", "stealthy-fetch", url, tmp_path,
         "--ai-targeted", "--network-idle", "--timeout", str(timeout * 1000)],
        [scrapling_bin, "extract", "fetch", url, tmp_path,
         "--ai-targeted", "--network-idle", "--timeout", str(timeout * 1000)],
    ]
    last_error = None
    for cmd in strategies:
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30, check=True)
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            if content.strip():
                os.unlink(tmp_path)
                return content
        except Exception as e:
            last_error = str(e)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise RuntimeError(f"scrapling failed: {last_error}")


def fetch_page(url: str, timeout: int = 20) -> str:
    """Try multiple strategies in order of preference."""
    errors = []

    # 1. curl_cffi (lightweight, auto-installs, Chrome TLS fingerprint)
    try:
        return fetch_curl_cffi(url, timeout)
    except RuntimeError as e:
        errors.append(str(e))

    # 2. scrapling (best anti-bot, but needs Playwright)
    try:
        return fetch_scrapling(url, timeout)
    except RuntimeError as e:
        errors.append(str(e))

    # 3. curl subprocess
    try:
        return fetch_curl(url, timeout)
    except RuntimeError as e:
        errors.append(str(e))

    # 4. urllib (last resort)
    try:
        return fetch_urllib(url, timeout)
    except RuntimeError as e:
        errors.append(str(e))

    raise RuntimeError(
        "All fetch strategies failed:\n" + "\n".join(f"  - {e}" for e in errors)
    )


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def score_item(item: Dict, vertical: str) -> int:
    title = item.get("title", "")
    score = 0

    # Vertical match
    keywords = set()
    for vert_key, kws in VERTICAL_KEYWORDS.items():
        if vert_key in vertical:
            keywords.update(kws)
    # Also add the vertical name itself
    for part in re.split(r"[/、，,\s]+", vertical):
        if part:
            keywords.add(part)

    matched = sum(1 for kw in keywords if kw.lower() in title.lower())
    if matched >= 3:
        score += 5
    elif matched >= 1:
        score += 3

    # Rank bonus
    rank = item.get("rank", 999)
    if rank <= 5:
        score += 3
    elif rank <= 10:
        score += 2
    elif rank <= 20:
        score += 1

    # Controversy / action value signals
    controversy_words = ["争议", "翻车", "道歉", "回应", "反转", "曝光", "内幕", "揭秘", "背后"]
    if any(w in title for w in controversy_words):
        score += 3

    # Trend / method signals
    trend_words = ["趋势", "未来", "时代", "变革", "革命", "首次", "突破", "宣布", "发布"]
    if any(w in title for w in trend_words):
        score += 3

    # Title penalty
    clickbait_words = ["震惊", "惊呆", "居然", "竟然", "不敢相信"]
    if any(w in title for w in clickbait_words):
        score -= 3

    return score


def rank_items(items: List[Dict], vertical: str, top_n: int = 10) -> List[Dict]:
    scored = []
    for item in items:
        s = score_item(item, vertical)
        scored.append({**item, "score": s, "vertical": vertical})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


# ---------------------------------------------------------------------------
# Feishu (Lark) Publishing
# ---------------------------------------------------------------------------

def run_lark_cli(args: List[str], timeout: int = 30) -> Dict:
    lark_bin = shutil.which("lark-cli")
    if not lark_bin:
        raise RuntimeError("lark-cli not found. Install: npx @larksuite/cli@latest install")
    cmd = [lark_bin] + args
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"lark-cli error (exit {result.returncode}): {stderr[:500]}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"raw": stdout}


def create_feishu_doc(content_path: str, title: Optional[str] = None) -> Dict:
    abs_path = os.path.abspath(content_path)
    filename = os.path.basename(abs_path)
    work_dir = os.path.dirname(abs_path)

    # lark-cli @file requires relative path from cwd
    need_chdir = os.getcwd() != work_dir
    prev_dir = None
    if need_chdir:
        prev_dir = os.getcwd()
        os.chdir(work_dir)

    try:
        args = [
            "docs", "+create",
            "--markdown", f"@{filename}",
        ]
        if title:
            args.extend(["--title", title])

        return run_lark_cli(args)
    finally:
        if prev_dir is not None:
            os.chdir(prev_dir)


def set_feishu_public(doc_token: str, doc_type: str = "docx") -> Dict:
    args = [
        "drive", "permission.public", "patch",
        "--params", json.dumps({"token": doc_token, "type": doc_type}),
        "--data", json.dumps({
            "external_access": True,
            "link_share_entity": "anyone_readable",
            "security_entity": "anyone_can_view",
            "comment_entity": "anyone_can_view",
            "share_entity": "anyone",
            "invite_external": True,
        }),
        "--as", "user",
        "--yes",
    ]
    return run_lark_cli(args)


def extract_doc_token(result: Dict) -> Optional[str]:
    for key in ["document_id", "doc_token", "document_token", "token", "id"]:
        if key in result:
            return result[key]
    data = result.get("data", {})
    for key in ["document_id", "doc_token", "document_token", "token", "id"]:
        if key in data:
            return data[key]
    url = result.get("url", result.get("data", {}).get("url", ""))
    if url:
        m = re.search(r"/docx/([A-Za-z0-9]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"/docs/([A-Za-z0-9]+)", url)
        if m:
            return m.group(1)
    return None


def extract_doc_url(result: Dict) -> Optional[str]:
    for key in ["url", "document_url"]:
        if key in result:
            return result[key]
    data = result.get("data", {})
    for key in ["url", "document_url"]:
        if key in data:
            return data[key]
    return None


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_fetch(args) -> Dict:
    url = args.url or TOPHUB_WECHAT_URL
    out_path = args.out or os.path.join(tempfile.gettempdir(), "tophub_wechat.json")

    result = {"ok": False, "source": url, "items": [], "error": None}

    try:
        raw_html = fetch_page(url)
        items = extract_items_from_html(raw_html)
        if not items:
            raise RuntimeError(
                "No items parsed. Page may be blocked, structure changed, "
                "or returned a challenge page. Try: scrapling extract stealthy-fetch"
            )
        result["ok"] = True
        result["items"] = items
        result["count"] = len(items)
    except Exception as e:
        result["error"] = str(e)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["ok"]:
        sys.exit(1)
    return result


def cmd_rank(args) -> Dict:
    items_path = args.items
    vertical = args.vertical or "科技/AI/互联网"
    top_n = args.top or 10
    out_path = args.out or os.path.join(tempfile.gettempdir(), "tophub_ranked.json")

    with open(items_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print(json.dumps({"ok": False, "error": "No items to rank"}, ensure_ascii=False))
        sys.exit(1)

    ranked = rank_items(items, vertical, top_n)

    result = {
        "ok": True,
        "vertical": vertical,
        "total_items": len(items),
        "top": ranked,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def cmd_publish(args) -> Dict:
    content_path = args.content
    title = getattr(args, "title", None)
    make_public = getattr(args, "public", False)
    out_path = args.out or os.path.join(tempfile.gettempdir(), "feishu_publish.json")

    result = {"ok": False, "doc_url": None, "doc_token": None, "public": False, "error": None}

    try:
        # Create doc
        doc_result = create_feishu_doc(content_path, title)
        doc_token = extract_doc_token(doc_result)
        doc_url = extract_doc_url(doc_result)
        result["doc_url"] = doc_url
        result["doc_token"] = doc_token
        result["create_result"] = doc_result

        # Set public
        if make_public and doc_token:
            try:
                pub_result = set_feishu_public(doc_token)
                result["public"] = True
                result["public_result"] = pub_result
            except Exception as e:
                result["public_error"] = str(e)

        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["ok"]:
        sys.exit(1)
    return result


def cmd_full(args) -> Dict:
    url = args.url or TOPHUB_WECHAT_URL
    vertical = args.vertical or "科技/AI/互联网"
    top_n = args.top or 10
    out_path = args.out or os.path.join(tempfile.gettempdir(), "wechat_hot_full.json")

    result = {"ok": False, "source": url, "vertical": vertical, "items": [], "ranked": [], "error": None}

    try:
        raw_html = fetch_page(url)
        items = extract_items_from_html(raw_html)
        if not items:
            raise RuntimeError("No items parsed from page")
        result["items"] = items
        result["count"] = len(items)

        ranked = rank_items(items, vertical, top_n)
        result["ranked"] = ranked
        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["ok"]:
        sys.exit(1)
    return result


# ---------------------------------------------------------------------------
# Search reliable sources (bypass WeChat anti-bot)
# ---------------------------------------------------------------------------

RELIABLE_SOURCES = [
    # --- AI（内建 AIHOT API） ---
    {"name": "AIHOT", "vertical": "AI", "api": "aihot"},
    # --- 科技 ---
    {"name": "36氪", "vertical": "科技", "search_template": "https://www.36kr.com/search/articles/{query}"},
    {"name": "虎嗅", "vertical": "科技", "search_template": "https://www.huxiu.com/search?s={query}"},
    {"name": "MIT科技评论", "vertical": "科技", "search_template": "https://www.technologyreview.com/?s={query}"},
    {"name": "爱范儿", "vertical": "科技", "search_template": "https://www.ifanr.com/?s={query}"},
    # --- 财经 ---
    {"name": "第一财经", "vertical": "财经", "search_template": "https://www.yicai.com/search?keys={query}"},
    {"name": "财新", "vertical": "财经", "search_template": "https://www.caixin.com/search?keyword={query}"},
    # --- 教育 ---
    {"name": "教育部", "vertical": "教育", "search_template": "https://www.moe.gov.cn/jyb_xxgk/s5743/s5744/"},
    {"name": "中国教育在线", "vertical": "教育", "search_template": "https://www.eol.cn/search/?keywords={query}"},
    # --- 健康 ---
    {"name": "WHO", "vertical": "健康", "search_template": "https://www.who.int/zh/search?query={query}"},
    {"name": "AHA", "vertical": "健康", "search_template": "https://www.heart.org/en/search?q={query}"},
    {"name": "PubMed", "vertical": "健康", "search_template": "https://pubmed.ncbi.nlm.nih.gov/?term={query}&format=abstract&size=5"},
    {"name": "丁香医生", "vertical": "健康", "search_template": "https://www.dxy.com/search?keyword={query}"},
    {"name": "果壳", "vertical": "健康", "search_template": "https://www.guokr.com/search?q={query}"},
    {"name": "CDC", "vertical": "健康", "search_template": "https://www.cdc.gov/search/index.html?searchquery={query}"},
    # --- 消费 ---
    {"name": "消费者报道", "vertical": "消费", "search_template": "https://www.thepaper.cn/search?keywordWord={query}"},
    # --- 职场 ---
    {"name": "澎湃新闻", "vertical": "职场", "search_template": "https://www.thepaper.cn/search?keywordWord={query}"},
    # --- 娱乐 ---
    {"name": "豆瓣", "vertical": "娱乐", "search_template": "https://www.douban.com/search?q={query}"},
    # --- 通用 ---
    {"name": "澎湃新闻", "vertical": "通用", "search_template": "https://www.thepaper.cn/search?keywordWord={query}"},
]


def search_reliable_sources(query: str, vertical: str = "", timeout: int = 15) -> List[Dict]:
    """Search reliable sources for topic-related content, filtered by vertical."""
    results = []
    encoded_query = urllib.request.quote(query)

    # Determine which verticals to include
    vert_set = set()
    for part in re.split(r"[/、，,\s]+", vertical):
        if part:
            vert_set.add(part)
    vert_set.add("通用")

    for source in RELIABLE_SOURCES:
        # Filter by vertical
        src_vert = source.get("vertical", "通用")
        if src_vert != "通用" and src_vert not in vert_set:
            continue

        # Special handling for AIHOT API
        if source.get("api") == "aihot":
            try:
                aihot_ua = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36 aihot-skill/0.2.0"
                )
                aihot_url = f"https://aihot.virxact.com/api/public/items?mode=selected&q={encoded_query}&take=5"
                req = urllib.request.Request(aihot_url, headers={"User-Agent": aihot_ua})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    aihot_data = json.loads(resp.read().decode("utf-8"))

                for item in aihot_data.get("items", [])[:5]:
                    results.append({
                        "source": f"AIHOT · {item.get('source', '')}",
                        "vertical": "AI",
                        "url": item.get("url", ""),
                        "title": item.get("title", "")[:200],
                        "snippet": item.get("summary", "")[:500],
                        "status": "ok",
                    })
            except Exception as e:
                results.append({
                    "source": "AIHOT",
                    "vertical": "AI",
                    "url": "",
                    "title": "",
                    "snippet": "",
                    "status": "error",
                    "error": str(e)[:200],
                })
            continue

        search_url = source["search_template"].format(query=encoded_query)
        try:
            html_content = fetch_page(search_url, timeout=timeout)
            title_match = re.search(r"<title>([^<]+)</title>", html_content, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else ""

            snippet = ""
            for tag in ["p", "div", "article"]:
                p_match = re.search(
                    rf"<{tag}[^>]*>([^<]{{50,300}})</{tag}>",
                    html_content,
                    re.IGNORECASE | re.DOTALL,
                )
                if p_match:
                    snippet = p_match.group(1).strip()
                    snippet = re.sub(r"\s+", " ", snippet)
                    break

            if title or snippet:
                results.append({
                    "source": source["name"],
                    "vertical": src_vert,
                    "url": search_url,
                    "title": title[:200],
                    "snippet": snippet[:500],
                    "status": "ok",
                })
        except Exception as e:
            results.append({
                "source": source["name"],
                "vertical": src_vert,
                "url": search_url,
                "title": "",
                "snippet": "",
                "status": "error",
                "error": str(e)[:200],
            })

    return results


def cmd_search(args) -> Dict:
    query = args.query
    vertical = getattr(args, "vertical", "") or ""
    out_path = args.out or os.path.join(tempfile.gettempdir(), "topic_search.json")

    result = {
        "ok": True,
        "query": query,
        "vertical": vertical,
        "sources": [],
        "error": None,
    }

    try:
        sources = search_reliable_sources(query, vertical)
        result["sources"] = sources
        result["ok_count"] = sum(1 for s in sources if s["status"] == "ok")
    except Exception as e:
        result["error"] = str(e)
        result["ok"] = False

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="微信24h热文榜抓取 + 垂类评分 + 飞书文档发布",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p_fetch = sub.add_parser("fetch", help="抓取 TopHub 微信24h热文榜")
    p_fetch.add_argument("--url", default=TOPHUB_WECHAT_URL)
    p_fetch.add_argument("--out", help="输出 JSON 路径")

    # rank
    p_rank = sub.add_parser("rank", help="按垂类关键词评分排序")
    p_rank.add_argument("--items", required=True, help="fetch 输出的 JSON 路径")
    p_rank.add_argument("--vertical", default="科技/AI/互联网")
    p_rank.add_argument("--top", type=int, default=10)
    p_rank.add_argument("--out", help="输出 JSON 路径")

    # publish
    p_pub = sub.add_parser("publish", help="用 lark-cli 创建飞书文档并设置权限")
    p_pub.add_argument("--content", required=True, help="Markdown 文件路径")
    p_pub.add_argument("--title", help="文档标题")
    p_pub.add_argument("--public", action="store_true", help="设置为互联网可读")
    p_pub.add_argument("--out", help="输出 JSON 路径")

    # search
    p_search = sub.add_parser("search", help="搜索可靠来源补充选题背景")
    p_search.add_argument("--query", required=True, help="搜索关键词")
    p_search.add_argument("--vertical", default="", help="垂类过滤，如 健康/科技/财经")
    p_search.add_argument("--out", help="输出 JSON 路径")

    # full (fetch + rank combined)
    p_full = sub.add_parser("full", help="抓取 + 评分一步到位")
    p_full.add_argument("--url", default=TOPHUB_WECHAT_URL)
    p_full.add_argument("--vertical", default="科技/AI/互联网")
    p_full.add_argument("--top", type=int, default=10)
    p_full.add_argument("--out", help="输出 JSON 路径")

    args = parser.parse_args()

    commands = {
        "fetch": cmd_fetch,
        "rank": cmd_rank,
        "search": cmd_search,
        "publish": cmd_publish,
        "full": cmd_full,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
