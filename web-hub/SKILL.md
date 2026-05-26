---
name: web-hub
description: "Unified web access hub — smart routing across Brave/Tavily/WebFetch/CDP/Playwright/Scrapling. Use when the task involves searching, browsing, scraping, extracting data from the web, or interacting with websites."
---

# Web Hub — Unified Web Access

Version: 1.0.0

All internet operations route through this skill when available: search, scrape, browse, interact, extract.
It is designed to keep the Claude Code workflow intact while giving Codex a clear fallback path.

## Runtime Compatibility

This skill supports two host environments:

- **Claude Code**: `CLAUDE_SKILL_DIR` points at this skill directory. Keep using the commands below exactly as written.
- **Codex**: if `CLAUDE_SKILL_DIR` is not set, resolve the skill root from the loaded `SKILL.md` path.

When a command shows `${CLAUDE_SKILL_DIR}`, Codex should substitute the resolved skill root. On Windows PowerShell, set `$SKILL_ROOT` to that resolved path:

```powershell
$SKILL_ROOT = "<resolved web-hub skill root>"
node "$SKILL_ROOT/scripts/check-deps.mjs" --check-only
```

Do not assume every tool named in the matrix is bundled here. This skill bundles the CDP proxy scripts and local bookmark/history search. Brave, Tavily, WebFetch/fetch, Context7, Playwright, Scrapling, and screenshot tools are host-provided capabilities; use whichever are actually available in the current agent.

## Pre-Flight

For a no-side-effect environment summary:

```bash
node "${CLAUDE_SKILL_DIR}/scripts/doctor.mjs"
```

Run environment check before first CDP operation:

```bash
node "${CLAUDE_SKILL_DIR}/scripts/check-deps.mjs"
```

Use `--check-only` when you need a no-side-effect diagnostic pass:

```bash
node "${CLAUDE_SKILL_DIR}/scripts/check-deps.mjs" --check-only
```

Note: This command creates `config.env` from template on first run (safe copy, no overwrite), then checks browser debug access and starts the local CDP proxy if needed.
With `--check-only`, it still checks Node/browser/config state but does not start the proxy.

Exit codes: `0` = proceed, `2` = ask user for browser preference (chrome/edge), `1` = follow error guidance.

Before CDP browser automation on social platforms, warn user about automation detection risks.

## Core Philosophy

**Think like a human**: define success first, pick the most direct path, validate each step, pivot when evidence says so.

1. **Receive request** — what does "done" look like?
2. **Choose entry point** — use the decision matrix below
3. **Validate in-process** — each result is evidence; don't retry failed approaches
4. **Complete** — stop when success criteria are met

**Search engines are discovery tools, not proof.** Always seek primary sources. When only secondary reporting is available, disclose it.

## Tool Routing

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

Host-specific mapping:

- **Claude Code**: use Claude's configured MCP/tools for Brave, Tavily, WebFetch, Playwright, Scrapling, and screenshots; use the bundled scripts for CDP and local browser data.
- **Codex**: prefer built-in web/fetch/search tools for public web work, Context7 for library docs, Browser for local app inspection, Chrome for profile/authenticated remote pages, Playwright for scripted public flows, and this skill's CDP proxy only when login state, real-browser fingerprint, or local browser data is required.
- If a named host tool is unavailable, say so briefly and choose the next lowest-cost available path. Do not invent a missing tool result.

## CDP Browser Mode

Connects to your **daily browser** (Chrome/Edge) via CDP Proxy, carrying existing login state. Operations run in background tabs — your existing tabs stay untouched.

### Setup (one-time)

**Chrome** (需要同时加两个参数):
```bash
# 先关闭所有 Chrome 窗口，再用以下命令启动
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data"
```

Safer Windows helper:

```powershell
$SKILL_ROOT = "<resolved web-hub skill root>"
& "$SKILL_ROOT/scripts/launch-chrome.cmd"
```

This helper asks before force-closing Chrome.

**Edge** (地址栏打开即可):
1. `edge://inspect/#remote-debugging`
2. 勾选 "Allow remote debugging for this browser instance"

Set preference in `config.env`: `WEB_ACCESS_BROWSER=chrome` or `edge`. `CDP_PROXY_PORT` and `CDP_TAB_IDLE_TIMEOUT` are also read from `config.env`; environment variables with the same names override the file for one run.
For temporary or nonstandard debug ports, set `WEB_HUB_CDP_PORTS=port1,port2` or `CDP_BROWSER_PORT=port`.

If `--check-only` reports a browser mismatch, do not keep retrying. Ask the user to enable remote debugging for the configured browser, or temporarily pass `--browser chrome|edge` only after confirming that browser is actually configured for remote debugging.

### Proxy API (localhost:3456)

All endpoints require `Authorization: Bearer <token>` (token printed to console on proxy startup, stored in `$TMPDIR/cdp-proxy-token`, or `%TEMP%/cdp-proxy-token` on Windows). `/health` is the only exception.

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

Claude Code / bash:

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

Codex / Windows PowerShell example:

```powershell
# 1. Ensure proxy is running
$SKILL_ROOT = "<resolved web-hub skill root>"
node "$SKILL_ROOT/scripts/check-deps.mjs"

# 2. Read token
$TOKEN = Get-Content -Raw "$env:TEMP/cdp-proxy-token"
$TOKEN = $TOKEN.Trim()

# 3. Open page
curl.exe -X POST -H "Authorization: Bearer $TOKEN" --data-raw "https://example.com" "http://localhost:3456/new"

# 4. Extract content
curl.exe -X POST -H "Authorization: Bearer $TOKEN" --data-raw "document.title" "http://localhost:3456/eval?target=TARGET_ID"

# 5. Cleanup
curl.exe -H "Authorization: Bearer $TOKEN" "http://localhost:3456/close?target=TARGET_ID"
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

### Verification Levels

- **Skill schema**: run Codex `quick_validate.py` against the skill directory.
- **Script syntax**: run `node --check` on scripts in `scripts/`.
- **Doctor summary**: run `doctor.mjs`; it does not start the proxy and summarizes root/config/browser/sqlite3 status.
- **No-side-effect environment check**: run `check-deps.mjs --check-only`; this may read/create `config.env` but does not start the proxy.
- **Proxy shell check**: start `cdp-proxy.mjs` on a temporary `CDP_PROXY_PORT`, call `/health`, then stop it.
- **Safe end-to-end CDP smoke test**: run `e2e-cdp-smoke.mjs`; it starts Chrome/Edge with a temporary profile and temporary ports, creates a tab, evaluates `document.title`, closes the tab, then cleans up.
- **Daily-browser CDP check**: requires Chrome or Edge remote debugging to be enabled in the user's real profile; then run `check-deps.mjs`, create a tab with `/new`, evaluate `document.title`, and close the tab.

Treat lower-level checks as partial evidence only. Do not claim daily-browser CDP success until the real browser debug step and `/new` → `/eval` → `/close` path have passed. The smoke test proves the bundled proxy workflow, not the user's logged-in browser session.

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
node "${CLAUDE_SKILL_DIR}/scripts/find-url.mjs" [keywords] [--only bookmarks|history] [--limit N] [--since 1d|7d] [--browser edge] [--all] [--full-url]
```

- `--all`: Bypass the keyword requirement for history search (still masks URL query/hash by default).
- `--full-url`: Show full URLs including query parameters and hash fragments.
- Windows history search requires `sqlite3`; install with `winget install sqlite.sqlite` if missing.

Privacy: URL query/hash are hidden by default to avoid leaking tokens, SSO callbacks, or sensitive parameters. Use `--full-url` to reveal them.

Use this **before** web search when the target might be in your local browser data.

## Parallel Research

When multiple independent research targets exist:

1. Split into sub-agents only if the host supports them
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

Codex PowerShell example:

```powershell
$SKILL_ROOT = "<resolved web-hub skill root>"
Get-ChildItem -LiteralPath "$SKILL_ROOT/references/site-patterns"
```

## Token Optimization

- In Codex, use host-provided output-limiting helpers such as `rtk` when available; in Claude Code, follow the host's token-reduction hooks.
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
