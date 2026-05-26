#!/usr/bin/env node
// End-to-end CDP smoke test using a temporary browser profile.

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkPort } from './browser-discovery.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PROXY_SCRIPT = path.join(ROOT, 'scripts', 'cdp-proxy.mjs');
const PROFILE_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'web-hub-chrome-profile-'));

function parsePort(name, fallback) {
  const raw = process.env[name] ?? fallback;
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0 || value >= 65536) throw new Error(`${name} must be a valid TCP port`);
  return value;
}

async function findOpenPort(start) {
  for (let port = start; port < start + 100; port++) {
    if (!(await checkPort(port))) return port;
  }
  throw new Error(`No open port found from ${start} to ${start + 99}`);
}

function findChrome() {
  const candidates = os.platform() === 'win32'
    ? [
        'C:/Program Files/Google/Chrome/Application/chrome.exe',
        'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
        'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
        'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
      ]
    : [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        '/usr/bin/google-chrome',
        '/usr/bin/chromium',
        '/usr/bin/microsoft-edge',
      ];
  return candidates.find(p => fs.existsSync(p));
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForPort(port, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await checkPort(port)) return true;
    await sleep(250);
  }
  return false;
}

function readToken() {
  return fs.readFileSync(path.join(os.tmpdir(), 'cdp-proxy-token'), 'utf8').trim();
}

async function fetchJson(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  try { return JSON.parse(text); }
  catch { throw new Error(`Non-JSON response ${res.status}: ${text.slice(0, 200)}`); }
}

async function main() {
  const browserPath = findChrome();
  if (!browserPath) throw new Error('Chrome or Edge executable not found');
  const browserPort = process.env.CDP_BROWSER_PORT ? parsePort('CDP_BROWSER_PORT') : await findOpenPort(49222);
  const proxyPort = process.env.CDP_PROXY_PORT ? parsePort('CDP_PROXY_PORT') : await findOpenPort(browserPort + 1);

  const browser = spawn(browserPath, [
    `--remote-debugging-port=${browserPort}`,
    `--user-data-dir=${PROFILE_DIR}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    'about:blank',
  ], { stdio: 'ignore', windowsHide: true });

  const browserReady = await waitForPort(browserPort);
  if (!browserReady) throw new Error(`Browser debug port ${browserPort} did not open`);

  const proxyEnv = {
    ...process.env,
    CDP_PROXY_PORT: String(proxyPort),
    WEB_HUB_CDP_PORTS: String(browserPort),
  };
  const proxy = spawn(process.execPath, [PROXY_SCRIPT], {
    env: proxyEnv,
    stdio: 'ignore',
    windowsHide: true,
  });

  try {
    const proxyReady = await waitForPort(proxyPort);
    if (!proxyReady) throw new Error(`Proxy port ${proxyPort} did not open`);

    const token = readToken();
    const auth = { Authorization: `Bearer ${token}` };
    const health = await fetchJson(`http://127.0.0.1:${proxyPort}/health`);
    const created = await fetchJson(`http://127.0.0.1:${proxyPort}/new`, {
      method: 'POST',
      headers: auth,
      body: 'data:text/html,<title>Web Hub Smoke</title><h1>ok</h1>',
    });
    if (!created.targetId) throw new Error('Missing targetId from /new');
    const evalResult = await fetchJson(`http://127.0.0.1:${proxyPort}/eval?target=${created.targetId}`, {
      method: 'POST',
      headers: auth,
      body: 'document.title',
    });
    await fetchJson(`http://127.0.0.1:${proxyPort}/close?target=${created.targetId}`, { headers: auth });
    if (evalResult.value !== 'Web Hub Smoke') throw new Error(`Unexpected document.title: ${evalResult.value}`);

    console.log(JSON.stringify({
      status: 'ok',
      browserPort,
      proxyPort,
      connected: health.connected ?? null,
      title: evalResult.value,
      profileDir: PROFILE_DIR,
    }, null, 2));
  } finally {
    if (!proxy.killed) proxy.kill();
    if (!browser.killed) browser.kill();
    await sleep(500);
    try { fs.rmSync(PROFILE_DIR, { recursive: true, force: true }); } catch {}
  }
}

await main();
