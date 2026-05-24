---
name: web-hub
description: "Unified web access hub — smart routing across Brave/Tavily/WebFetch/CDP/Playwright/Scrapling. Use when the task involves searching, browsing, scraping, extracting data from the web, or interacting with websites."
version: "1.0.0"
---

# Web Hub — Unified Web Access

All internet operations route through this skill: search, scrape, browse, interact, extract.

## Pre-Flight

Run environment check before first CDP operation:

```bash
node "${CLAUDE_SKILL_DIR}/scripts/check-deps.mjs"
```

Note: This command creates `config.env` from template on first run (safe copy, no overwrite).

Exit codes: `0` = proceed, `2` = ask user for browser preference (chrome/edge), `1` = follow error guidance.

Before CDP browser automation on social platforms, warn user about automation detection risks.

## Core Philosophy

**Think like a human**: define success first, pick the most direct path, validate each step, pivot when evidence says so.

1. **Receive request** — what does "done" look like?
2. **Choose entry point** — use the decision matrix below
3. **Validate in-process** — each result is evidence; don't retry failed approaches
4. **Complete** — stop when success criteria are met

**Search engines are discovery tools, not proof.** Always seek primary sources. When only secondary reporting is available, disclose it.

## Decision Matrix

Choose the **lowest-cost tool** that can accomplish the goal:

| Scenario | Tool | Why |
|----------|------|-----|
| **Keyword search, discovery** | **Brave Search** | Fast, 20 results, pagination |
| **Deep research, multiple sources** | **Tavily Search** (advanced) | Structured, can fetch raw HTML |
| **Known URL, text content** | **WebFetch** | Direct, no overhead |
| **Known URL, save tokens** | **Tavily Extract** | Clean structured extraction |
| **Known URL, anti-scraping** | **CDP Browser** or **Scrapling** | Real browser fingerprint |
| **Login-required content** | **CDP Browser** | Carries your login session |
| **Interactive navigation (click, fill, scroll)** | **CDP Browser** or **Playwright MCP** | Full browser control |
| **Dynamic JS-rendered page** | **CDP Browser** or **Playwright MCP** | Executes JavaScript |
| **Bulk crawl, site map** | **Tavily Crawl/Map** | Parallel, structured |
| **Video frame capture** | **CDP Browser** | Control `<video>` element |
| **File upload to web form** | **CDP Browser** (`/setFiles`) | Bypasses file dialog |
| **Local bookmarks/history** | **find-url.mjs** | Chrome/Edge local data |
| **Library/framework docs** | **Context7 MCP** | Always current |
| **Anti-bot (Cloudflare etc.)** | **Scrapling** (StealthyFetcher) | Built-in challenge solving |
| **Desktop screenshot** | **Screenshot skill** | OS-level capture |

## CDP Browser Mode

Connects to your **daily browser** (Chrome/Edge) via CDP Proxy, carrying existing login state. Operations run in background tabs — your existing tabs stay untouched.

### Setup (one-time)

**Chrome** (需要同时加两个参数):
```bash
# 先关闭所有 Chrome 窗口，再用以下命令启动
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data"
```

**Edge** (地址栏打开即可):
1. `edge://inspect/#remote-debugging`
2. 勾选 "Allow remote debugging for this browser instance"

3. Set preference in `config.env`: `WEB_ACCESS_BROWSER=chrome` 或 `edge`

### Proxy API (localhost:3456)

All endpoints require `Authorization: Bearer <token>` (token printed to console on proxy startup, stored in `$TMPDIR/cdp-proxy-token`). `/health` is the only exception.

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/health` | GET | — | Check proxy status |
| `/targets` | GET | — | List open tabs |
| `/new` | POST | URL | Create background tab, auto-wait load |
| `/close?target=ID` | GET | — | Close tab |
| `/navigate?target=ID` | POST | URL | Navigate, auto-wait load |
| `/back?target=ID` | GET | — | Go back |
| `/info?target=ID` | GET | — | Page title/url/readyState |
| `/eval?target=ID` | POST | JS expression | Execute JavaScript, return `{value}` |
| `/click?target=ID` | POST | CSS selector | JS click (scrollIntoView + el.click()) |
| `/clickAt?target=ID` | POST | CSS selector | Real mouse event (bypasses anti-automation) |
| `/setFiles?target=ID` | POST | JSON `{selector, files}` | Upload files to input |
| `/scroll?target=ID&direction=down` | GET | — | Scroll (down/up/top/bottom) |
| `/screenshot?target=ID` | GET | — | Capture screenshot (returns image binary). Add `&file=name.png` to save to `$TMPDIR/cdp-screenshots/` (image extensions only, no overwrite) |

URLs go in POST body (not query string) to avoid truncation.

### Usage Pattern

```bash
# 1. Ensure proxy is running
node "${CLAUDE_SKILL_DIR}/scripts/check-deps.mjs"

# 2. Read token (printed to console, or read from file)
TOKEN=$(cat "$TMPDIR/cdp-proxy-token")

# 3. Open page
curl -X POST -H "Authorization: Bearer $TOKEN" --data-raw 'https://example.com' http://localhost:3456/new
# → {"targetId": "ABC123"}

# 4. Extract content
curl -X POST -H "Authorization: Bearer $TOKEN" --data-raw 'document.title' http://localhost:3456/eval?target=ABC123
# → {"value": "Example Domain"}

# 5. Interact
curl -X POST -H "Authorization: Bearer $TOKEN" --data-raw 'a.link' http://localhost:3456/click?target=ABC123

# 6. Cleanup
curl -H "Authorization: Bearer $TOKEN" http://localhost:3456/close?target=ABC123
```

### Key Technical Facts

- DOM contains loaded-but-hidden content (carousel frames, collapsed sections, lazy-load placeholders)
- Shadow DOM and iframe boundaries exist; recursive eval can penetrate all layers
- Scrolling triggers lazy-loaded images before extraction
- Self-created tabs must be closed; user tabs stay untouched
- Proxy stays running — restarting requires re-authorization in browser
- Tabs auto-close after 15 min idle (configurable via `CDP_TAB_IDLE_TIMEOUT`)
- The proxy intercepts page probes of Chrome debug port (anti-fingerprinting)

### Login Handling

Try to get content first. Only prompt user to log in when content is confirmed inaccessible. After login, page refresh continues the task — no restart needed.

## CDP vs Playwright — When to Choose Which

| | CDP Proxy | Playwright MCP |
|---|---|---|
| **Login state** | Your real browser, logged in | Fresh instance, no cookies |
| **Fingerprint** | Real browser fingerprint | Automation fingerprint |
| **Setup** | Need debug toggle | Works out of box |
| **Best for** | Social platforms, internal systems, authenticated content | Testing, public sites, scripted flows |

**Rule of thumb**: If the task needs your login or the site has anti-bot, use CDP. Otherwise Playwright is simpler.

## Local Bookmark & History Search

For pages you've visited before (internal systems, SSO backends, intranet):

```bash
node "${CLAUDE_SKILL_DIR}/scripts/find-url.mjs [keywords] [--only bookmarks|history] [--limit N] [--since 1d|7d] [--browser edge] [--all] [--full-url]
```

- `--all`: Bypass the keyword requirement for history search (still masks URL query/hash by default).
- `--full-url`: Show full URLs including query parameters and hash fragments.

Privacy: URL query/hash are hidden by default to avoid leaking tokens, SSO callbacks, or sensitive parameters. Use `--full-url` to reveal them.

Use this **before** web search when the target might be in your local browser data.

## Parallel Research

When multiple independent research targets exist:

1. Split into sub-agents
2. Each sub-agent creates its own CDP tabs (shared browser, tab-level isolation)
3. Prompt sub-agents with **what** (goals), not **how** (specific tools)
4. Merge results

Don't split when targets have dependencies or tasks are lightweight.

## Site Experience

Before operating on a known site, check `references/site-patterns/{domain}.md` for accumulated knowledge. After successful operations, record verified patterns (not speculation).

```bash
# Check existing patterns
ls "${CLAUDE_SKILL_DIR}/references/site-patterns/"
```

## Token Optimization

- Use `rtk` proxy for git/test commands (auto via hook)
- Use Tavily Extract instead of full page fetch when only text is needed
- Use Jina (`r.jina.ai/URL`) to convert articles to Markdown (20 RPM limit)
- Pipe long outputs: `| head -c 4000`
- Use Brave for quick searches, Tavily advanced only when depth is needed

## Anti-Bot Strategy

Escalation order:
1. **WebFetch** — try first, lowest cost
2. **Tavily Extract** — structured extraction
3. **Scrapling StealthyFetcher** — Cloudflare bypass, stealth mode
4. **CDP Browser** — real browser with login state
5. **Playwright MCP** — full automation control

Never jump to the highest tier without trying simpler approaches first.
