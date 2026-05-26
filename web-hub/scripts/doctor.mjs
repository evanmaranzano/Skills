#!/usr/bin/env node
// Web Hub doctor - no-side-effect environment summary.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { selectBrowser, knownBrowsers } from './browser-discovery.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CONFIG_PATH = path.join(ROOT, 'config.env');
const REQUIRED_SCRIPTS = [
  'browser-discovery.mjs',
  'cdp-proxy.mjs',
  'check-deps.mjs',
  'e2e-cdp-smoke.mjs',
  'find-url.mjs',
  'launch-chrome.cmd',
];

function readConfig() {
  const cfg = {};
  let content;
  try { content = fs.readFileSync(CONFIG_PATH, 'utf8'); }
  catch { return cfg; }
  for (const line of content.split(/\r?\n/)) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const i = t.indexOf('=');
    if (i === -1) continue;
    const k = t.slice(0, i).trim();
    const v = t.slice(i + 1).trim();
    if (k && v) cfg[k] = v;
  }
  return cfg;
}

function commandExists(command, args = ['--version']) {
  try {
    execFileSync(command, args, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function printCheck(name, ok, detail = '') {
  const mark = ok ? 'ok' : 'warn';
  console.log(`${name}: ${mark}${detail ? ` (${detail})` : ''}`);
}

async function main() {
  const cfg = readConfig();
  const major = Number(process.versions.node.split('.')[0]);

  console.log(`skill-root: ${ROOT}`);
  printCheck('node', major >= 22, `v${process.versions.node}`);
  printCheck('config', fs.existsSync(CONFIG_PATH), CONFIG_PATH);
  if (Object.keys(cfg).length) {
    console.log(`config-values: WEB_ACCESS_BROWSER=${cfg.WEB_ACCESS_BROWSER || ''}, CDP_PROXY_PORT=${cfg.CDP_PROXY_PORT || '3456'}, CDP_TAB_IDLE_TIMEOUT=${cfg.CDP_TAB_IDLE_TIMEOUT || '900000'}`);
  }

  for (const script of REQUIRED_SCRIPTS) {
    const scriptPath = path.join(ROOT, 'scripts', script);
    printCheck(`script:${script}`, fs.existsSync(scriptPath), scriptPath);
  }

  printCheck('sqlite3', commandExists('sqlite3'), 'needed only for history search');

  const selected = await selectBrowser();
  if (selected.kind === 'ok') {
    console.log(`browser: ok (${selected.browser.label}, port ${selected.browser.port}, ${selected.source})`);
  } else {
    const configured = selected.configured || '';
    const detected = selected.detected?.map(b => `${b.id}:${b.port}`).join(', ') || 'none';
    console.log(`browser: warn (${selected.kind}; configured=${configured || 'none'}; detected=${detected})`);
    console.log(`browser-hint: enable remote debugging for ${configured || knownBrowsers().map(b => b.id).join('|')} before CDP end-to-end use`);
  }
}

await main();
