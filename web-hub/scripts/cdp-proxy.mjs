#!/usr/bin/env node
// CDP Proxy - 通过 HTTP API 操控用户日常浏览器（Chrome / Edge / Chromium）
// 要求：浏览器已开启 remote debugging（chrome://inspect#remote-debugging toggle）
// Node.js 22+（原生 WebSocket）

import http from 'node:http';
import crypto from 'node:crypto';
import { URL } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
import { selectBrowser, findFallbackPort } from './browser-discovery.mjs';

// --- 鉴权 Token ---
const AUTH_TOKEN = crypto.randomUUID();
const TOKEN_FILE = path.join(os.tmpdir(), 'cdp-proxy-token');
// mode 0o600 在 Windows 上被忽略（NTFS ACL），localhost 绑定已限制外部访问
try { fs.writeFileSync(TOKEN_FILE, AUTH_TOKEN, { mode: 0o600 }); } catch {}
console.log(`[CDP Proxy] Auth token written to: ${TOKEN_FILE}`);

const SCREENSHOT_DIR = path.join(os.tmpdir(), 'cdp-screenshots');
try { fs.mkdirSync(SCREENSHOT_DIR, { recursive: true }); } catch {}

// --- 解析 --browser 参数 ---
function parseBrowserArg() {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--browser' && argv[i + 1]) return argv[i + 1];
    if (argv[i].startsWith('--browser=')) return argv[i].slice('--browser='.length);
  }
  return null;
}
const BROWSER_OVERRIDE = parseBrowserArg();

const PORT = parseInt(process.env.CDP_PROXY_PORT || '3456');
let ws = null;
let cmdId = 0;
const pending = new Map();
const sessions = new Map();
const managedTabs = new Map();
const TAB_IDLE_TIMEOUT = parseInt(process.env.CDP_TAB_IDLE_TIMEOUT || '900000');
const CLEANUP_INTERVAL = 60000;

// --- WebSocket 兼容层 ---
let WS;
if (typeof globalThis.WebSocket !== 'undefined') {
  WS = globalThis.WebSocket;
} else {
  try { WS = (await import('ws')).default; }
  catch {
    console.error('[CDP Proxy] 错误：Node.js < 22 且未安装 ws 模块');
    process.exit(1);
  }
}

let connectedBrowser = null;
let pinnedBrowserId = null;

// --- 浏览器发现 ---
async function discoverChromePort() {
  const result = await selectBrowser(BROWSER_OVERRIDE);
  if (result.kind === 'ok') {
    if (pinnedBrowserId && pinnedBrowserId !== result.browser.id) {
      throw new Error(`已 pin ${pinnedBrowserId}，不会自动切到 ${result.browser.id}`);
    }
    pinnedBrowserId = result.browser.id;
    connectedBrowser = { id: result.browser.id, label: result.browser.label, source: result.source };
    const tag = result.source === 'override' ? '[--browser]' : '[config.env]';
    console.log(`[CDP Proxy] 选用 ${result.browser.label} (port ${result.browser.port}) ${tag}`);
    return { port: result.browser.port, wsPath: result.browser.wsPath };
  }
  if (result.kind === 'mismatch') {
    const expected = result.override || result.configured;
    throw new Error(`浏览器 "${expected}" 未连接，请在地址栏访问 ${expected}://inspect/#remote-debugging 启用`);
  }
  if (pinnedBrowserId) {
    throw new Error(`已连接 ${pinnedBrowserId}，现已断开。请重新打开浏览器调试开关`);
  }
  const fallback = await findFallbackPort();
  if (fallback !== null) {
    connectedBrowser = { id: 'unknown', label: '未知（手动调试端口）', source: 'fallback' };
    return { port: fallback.port, wsPath: fallback.wsPath };
  }
  return null;
}

function getWebSocketUrl(port, wsPath) {
  if (wsPath) return `ws://127.0.0.1:${port}${wsPath}`;
  return `ws://127.0.0.1:${port}/devtools/browser`;
}

// --- WebSocket 连接 ---
let chromePort = null;
let chromeWsPath = null;
let connectingPromise = null;

async function connect() {
  if (ws && (ws.readyState === WS.OPEN || ws.readyState === 1)) return;
  if (connectingPromise) return connectingPromise;

  if (!chromePort) {
    const discovered = await discoverChromePort();
    if (!discovered) {
      throw new Error('Chrome 未开启远程调试。请在地址栏访问 chrome://inspect/#remote-debugging 并启用');
    }
    chromePort = discovered.port;
    chromeWsPath = discovered.wsPath;
  }

  const wsUrl = getWebSocketUrl(chromePort, chromeWsPath);

  return connectingPromise = new Promise((resolve, reject) => {
    ws = new WS(wsUrl);

    const onOpen = () => {
      cleanup();
      connectingPromise = null;
      console.log(`[CDP Proxy] 已连接 (port ${chromePort})`);
      resolve();
    };
    const onError = (e) => {
      cleanup();
      connectingPromise = null;
      ws = null;
      chromePort = null;
      chromeWsPath = null;
      reject(new Error(e.message || '连接失败'));
    };
    const onClose = () => {
      console.log('[CDP Proxy] 连接断开');
      ws = null;
      chromePort = null;
      chromeWsPath = null;
      sessions.clear();
      managedTabs.clear();
    };
    const onMessage = (evt) => {
      const data = typeof evt === 'string' ? evt : (evt.data || evt);
      const msg = JSON.parse(typeof data === 'string' ? data : data.toString());

      if (msg.method === 'Target.attachedToTarget') {
        sessions.set(msg.params.targetInfo.targetId, msg.params.sessionId);
      }
      // 拦截页面对调试端口的探测（反风控）
      if (msg.method === 'Fetch.requestPaused') {
        const { requestId, sessionId: sid } = msg.params;
        sendCDP('Fetch.failRequest', { requestId, errorReason: 'ConnectionRefused' }, sid).catch(() => {});
      }
      if (msg.id && pending.has(msg.id)) {
        const { resolve, timer } = pending.get(msg.id);
        clearTimeout(timer);
        pending.delete(msg.id);
        resolve(msg);
      }
    };

    function cleanup() {
      ws.removeEventListener?.('open', onOpen);
      ws.removeEventListener?.('error', onError);
    }

    if (ws.on) {
      ws.on('open', onOpen);
      ws.on('error', onError);
      ws.on('close', onClose);
      ws.on('message', onMessage);
    } else {
      ws.addEventListener('open', onOpen);
      ws.addEventListener('error', onError);
      ws.addEventListener('close', onClose);
      ws.addEventListener('message', onMessage);
    }
  });
}

function sendCDP(method, params = {}, sessionId = null) {
  return new Promise((resolve, reject) => {
    if (!ws || (ws.readyState !== WS.OPEN && ws.readyState !== 1)) {
      return reject(new Error('WebSocket 未连接'));
    }
    const id = ++cmdId;
    const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('CDP 命令超时: ' + method));
    }, 30000);
    pending.set(id, { resolve, timer });
    ws.send(JSON.stringify(msg));
  });
}

const portGuardedSessions = new Set();

async function ensureSession(targetId) {
  if (sessions.has(targetId)) return sessions.get(targetId);
  const resp = await sendCDP('Target.attachToTarget', { targetId, flatten: true });
  if (resp.result?.sessionId) {
    const sid = resp.result.sessionId;
    sessions.set(targetId, sid);
    await enablePortGuard(sid);
    return sid;
  }
  throw new Error('attach 失败: ' + JSON.stringify(resp.error));
}

async function enablePortGuard(sessionId) {
  if (!chromePort || portGuardedSessions.has(sessionId)) return;
  try {
    await sendCDP('Fetch.enable', {
      patterns: [
        { urlPattern: `http://127.0.0.1:${chromePort}/*`, requestStage: 'Request' },
        { urlPattern: `http://localhost:${chromePort}/*`, requestStage: 'Request' },
      ]
    }, sessionId);
    portGuardedSessions.add(sessionId);
  } catch {}
}

// --- Tab 管理 ---
function touchTab(targetId) {
  const entry = managedTabs.get(targetId);
  if (entry) entry.lastAccessed = Date.now();
}

async function cleanupIdleTabs() {
  if (!ws || (ws.readyState !== WS.OPEN && ws.readyState !== 1)) return;
  const now = Date.now();
  for (const [targetId, info] of managedTabs) {
    if (now - info.lastAccessed < TAB_IDLE_TIMEOUT) continue;
    try { await sendCDP('Target.closeTarget', { targetId }); } catch {}
    sessions.delete(targetId);
    managedTabs.delete(targetId);
    console.log(`[CDP Proxy] Auto-closed idle tab: ${targetId}`);
  }
}

async function closeAllManagedTabs() {
  if (!ws || (ws.readyState !== WS.OPEN && ws.readyState !== 1)) return;
  for (const targetId of [...managedTabs.keys()]) {
    try { await sendCDP('Target.closeTarget', { targetId }); } catch {}
    sessions.delete(targetId);
    managedTabs.delete(targetId);
  }
}

// --- 页面加载等待 ---
async function waitForLoad(sessionId, timeoutMs = 15000) {
  await sendCDP('Page.enable', {}, sessionId);
  return new Promise((resolve) => {
    let done = false;
    const finish = (r) => { if (!done) { done = true; clearTimeout(t); clearInterval(c); resolve(r); } };
    const t = setTimeout(() => finish('timeout'), timeoutMs);
    const c = setInterval(async () => {
      try {
        const r = await sendCDP('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true }, sessionId);
        if (r.result?.result?.value === 'complete') finish('complete');
      } catch {}
    }, 500);
  });
}

async function readBody(req) {
  let body = '';
  for await (const chunk of req) body += chunk;
  return body;
}

// --- HTTP API ---
const server = http.createServer(async (req, res) => {
  const parsed = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = parsed.pathname;
  const q = Object.fromEntries(parsed.searchParams);
  if (q.target) touchTab(q.target);

  res.setHeader('Content-Type', 'application/json; charset=utf-8');

  // 鉴权：/health 免鉴权，其余端点强制 Bearer token
  if (pathname !== '/health') {
    const authHeader = req.headers['authorization'] || '';
    if (!authHeader.startsWith('Bearer ') || authHeader.slice(7) !== AUTH_TOKEN) {
      res.statusCode = 401;
      res.end(JSON.stringify({ error: 'Unauthorized. Provide Authorization: Bearer <token>' }));
      console.error(`[CDP Proxy] 拒绝未鉴权请求: ${req.method} ${pathname} from ${req.socket.remoteAddress}`);
      return;
    }
  }

  try {
    if (pathname === '/health') {
      const connected = ws && (ws.readyState === WS.OPEN || ws.readyState === 1);
      res.end(JSON.stringify({
        status: 'ok', connected, browser: connectedBrowser,
        sessions: sessions.size, managedTabs: managedTabs.size, chromePort,
      }));
      return;
    }

    await connect();

    if (pathname === '/targets') {
      const resp = await sendCDP('Target.getTargets');
      const pages = resp.result.targetInfos.filter(t => t.type === 'page');
      res.end(JSON.stringify(pages, null, 2));
    }

    else if (pathname === '/new') {
      if (req.method !== 'POST') { res.statusCode = 400; res.end(JSON.stringify({ error: 'POST required' })); return; }
      const body = (await readBody(req)).trim();
      const targetUrl = body || 'about:blank';
      const resp = await sendCDP('Target.createTarget', { url: targetUrl, background: true });
      const targetId = resp.result.targetId;
      managedTabs.set(targetId, { lastAccessed: Date.now() });
      if (targetUrl !== 'about:blank') {
        try { const sid = await ensureSession(targetId); await waitForLoad(sid); } catch {}
      }
      res.end(JSON.stringify({ targetId }));
    }

    else if (pathname === '/close') {
      const resp = await sendCDP('Target.closeTarget', { targetId: q.target });
      sessions.delete(q.target);
      managedTabs.delete(q.target);
      res.end(JSON.stringify(resp.result));
    }

    else if (pathname === '/navigate') {
      if (req.method !== 'POST') { res.statusCode = 400; res.end(JSON.stringify({ error: 'POST required' })); return; }
      const targetUrl = (await readBody(req)).trim();
      const sid = await ensureSession(q.target);
      const resp = await sendCDP('Page.navigate', { url: targetUrl }, sid);
      await waitForLoad(sid);
      res.end(JSON.stringify(resp.result));
    }

    else if (pathname === '/back') {
      const sid = await ensureSession(q.target);
      await sendCDP('Runtime.evaluate', { expression: 'history.back()' }, sid);
      await waitForLoad(sid);
      res.end(JSON.stringify({ ok: true }));
    }

    else if (pathname === '/eval') {
      const sid = await ensureSession(q.target);
      const body = await readBody(req);
      const expr = body || q.expr || 'document.title';
      const resp = await sendCDP('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }, sid);
      if (resp.result?.result?.value !== undefined) {
        res.end(JSON.stringify({ value: resp.result.result.value }));
      } else if (resp.result?.exceptionDetails) {
        res.statusCode = 400;
        res.end(JSON.stringify({ error: resp.result.exceptionDetails.text }));
      } else {
        res.end(JSON.stringify(resp.result));
      }
    }

    else if (pathname === '/click') {
      const sid = await ensureSession(q.target);
      const selector = await readBody(req);
      if (!selector) { res.statusCode = 400; res.end(JSON.stringify({ error: '需要 CSS 选择器' })); return; }
      const sj = JSON.stringify(selector);
      const js = `(() => {
        const el = document.querySelector(${sj});
        if (!el) return { error: '未找到: ' + ${sj} };
        el.scrollIntoView({ block: 'center' });
        el.click();
        return { clicked: true, tag: el.tagName, text: (el.textContent || '').slice(0, 100) };
      })()`;
      const resp = await sendCDP('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true }, sid);
      const val = resp.result?.result?.value;
      if (val?.error) { res.statusCode = 400; res.end(JSON.stringify(val)); }
      else res.end(JSON.stringify(val || resp.result));
    }

    else if (pathname === '/clickAt') {
      const sid = await ensureSession(q.target);
      const selector = await readBody(req);
      if (!selector) { res.statusCode = 400; res.end(JSON.stringify({ error: '需要 CSS 选择器' })); return; }
      const sj = JSON.stringify(selector);
      const js = `(() => {
        const el = document.querySelector(${sj});
        if (!el) return { error: '未找到: ' + ${sj} };
        el.scrollIntoView({ block: 'center' });
        const r = el.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2, tag: el.tagName, text: (el.textContent || '').slice(0, 100) };
      })()`;
      const coordResp = await sendCDP('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true }, sid);
      const coord = coordResp.result?.result?.value;
      if (!coord?.x && coord?.x !== 0) { res.statusCode = 400; res.end(JSON.stringify(coord || coordResp.result)); return; }
      await sendCDP('Input.dispatchMouseEvent', { type: 'mousePressed', x: coord.x, y: coord.y, button: 'left', clickCount: 1 }, sid);
      await sendCDP('Input.dispatchMouseEvent', { type: 'mouseReleased', x: coord.x, y: coord.y, button: 'left', clickCount: 1 }, sid);
      res.end(JSON.stringify({ clicked: true, ...coord }));
    }

    else if (pathname === '/setFiles') {
      const sid = await ensureSession(q.target);
      const body = JSON.parse(await readBody(req));
      if (!body.selector || !body.files) { res.statusCode = 400; res.end(JSON.stringify({ error: '需要 selector 和 files' })); return; }
      await sendCDP('DOM.enable', {}, sid);
      const doc = await sendCDP('DOM.getDocument', {}, sid);
      const node = await sendCDP('DOM.querySelector', { nodeId: doc.result.root.nodeId, selector: body.selector }, sid);
      if (!node.result?.nodeId) { res.statusCode = 400; res.end(JSON.stringify({ error: '未找到: ' + body.selector })); return; }
      await sendCDP('DOM.setFileInputFiles', { nodeId: node.result.nodeId, files: body.files }, sid);
      res.end(JSON.stringify({ success: true, files: body.files.length }));
    }

    else if (pathname === '/scroll') {
      const sid = await ensureSession(q.target);
      const y = parseInt(q.y || '3000');
      const dir = q.direction || 'down';
      let js;
      if (dir === 'top') js = 'window.scrollTo(0,0);"top"';
      else if (dir === 'bottom') js = 'window.scrollTo(0,document.body.scrollHeight);"bottom"';
      else if (dir === 'up') js = `window.scrollBy(0,-${Math.abs(y)});"up"`;
      else js = `window.scrollBy(0,${Math.abs(y)});"down"`;
      const resp = await sendCDP('Runtime.evaluate', { expression: js, returnByValue: true }, sid);
      await new Promise(r => setTimeout(r, 800));
      res.end(JSON.stringify({ value: resp.result?.result?.value }));
    }

    else if (pathname === '/screenshot') {
      const sid = await ensureSession(q.target);
      const format = q.format || 'png';
      const resp = await sendCDP('Page.captureScreenshot', { format, quality: format === 'jpeg' ? 80 : undefined }, sid);
      if (q.file) {
        const ALLOWED_EXTS = ['.png', '.jpeg', '.jpg', '.webp'];
        const ext = path.extname(q.file).toLowerCase();
        const basename = path.basename(q.file);
        if (!ALLOWED_EXTS.includes(ext)) {
          res.statusCode = 400;
          res.end(JSON.stringify({ error: `不支持的扩展名 "${ext}"，允许: ${ALLOWED_EXTS.join(', ')}` }));
          return;
        }
        const safePath = path.join(SCREENSHOT_DIR, basename);
        if (safePath !== path.resolve(safePath) || !safePath.startsWith(SCREENSHOT_DIR)) {
          res.statusCode = 400;
          res.end(JSON.stringify({ error: '非法路径' }));
          return;
        }
        if (fs.existsSync(safePath)) {
          res.statusCode = 409;
          res.end(JSON.stringify({ error: `文件已存在: ${safePath}` }));
          return;
        }
        fs.writeFileSync(safePath, Buffer.from(resp.result.data, 'base64'));
        res.end(JSON.stringify({ saved: safePath }));
      } else {
        res.setHeader('Content-Type', 'image/' + format);
        res.end(Buffer.from(resp.result.data, 'base64'));
      }
    }

    else if (pathname === '/info') {
      const sid = await ensureSession(q.target);
      const resp = await sendCDP('Runtime.evaluate', {
        expression: 'JSON.stringify({title:document.title,url:location.href,ready:document.readyState})',
        returnByValue: true,
      }, sid);
      res.end(resp.result?.result?.value || '{}');
    }

    else {
      res.statusCode = 404;
      res.end(JSON.stringify({
        error: '未知端点',
        endpoints: ['/health', '/targets', '/new', '/close', '/navigate', '/back', '/info', '/eval', '/click', '/clickAt', '/setFiles', '/scroll', '/screenshot'],
      }));
    }
  } catch (e) {
    res.statusCode = 500;
    res.end(JSON.stringify({ error: e.message }));
  }
});

// --- 启动 ---
function checkPortAvailable(port) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once('error', () => resolve(false));
    s.once('listening', () => { s.close(); resolve(true); });
    s.listen(port, '127.0.0.1');
  });
}

async function main() {
  const available = await checkPortAvailable(PORT);
  if (!available) {
    try {
      const ok = await new Promise((resolve) => {
        http.get(`http://127.0.0.1:${PORT}/health`, { timeout: 2000 }, (res) => {
          let d = '';
          res.on('data', c => d += c);
          res.on('end', () => resolve(d.includes('"ok"')));
        }).on('error', () => resolve(false));
      });
      if (ok) { console.log(`[CDP Proxy] 已有实例运行在 port ${PORT}，退出`); process.exit(0); }
    } catch {}
    console.error(`[CDP Proxy] 端口 ${PORT} 已被占用`);
    process.exit(1);
  }

  server.listen(PORT, '127.0.0.1', () => {
    console.log(`[CDP Proxy] http://localhost:${PORT}`);
    connect().catch(e => console.error('[CDP Proxy] 初始连接失败:', e.message, '（首次请求时重试）'));
  });

  const cleanupTimer = setInterval(cleanupIdleTabs, CLEANUP_INTERVAL);
  cleanupTimer.unref();

  const shutdown = async (sig) => {
    console.log(`[CDP Proxy] ${sig}`);
    clearInterval(cleanupTimer);
    await closeAllManagedTabs();
    process.exit(0);
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

process.on('uncaughtException', (e) => console.error('[CDP Proxy] 未捕获异常:', e.message));
process.on('unhandledRejection', (e) => console.error('[CDP Proxy] 未处理拒绝:', e?.message || e));

main();
