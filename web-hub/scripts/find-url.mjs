#!/usr/bin/env node
// find-url - 从本地 Chrome/Edge 书签/历史中检索 URL
// 用于定位公网搜索覆盖不到的目标（内部系统、SSO 后台、内网域名等）
//
// 用法：
//   node find-url.mjs [关键词...] [--only bookmarks|history] [--limit N] [--since 1d|7h|YYYY-MM-DD]
//   node find-url.mjs 财务小智
//   node find-url.mjs github --since 7d --only history
//   node find-url.mjs --since 7d --only history --sort visits
//   node find-url.mjs github --browser edge

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execFileSync } from 'node:child_process';

function parseArgs(argv) {
  const a = { keywords: [], only: null, browser: null, limit: 20, since: null, sort: 'recent', all: false, fullUrl: false };
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === '--only')         a.only    = argv[++i];
    else if (v === '--browser') a.browser = argv[++i];
    else if (v === '--limit')   a.limit   = parseInt(argv[++i], 10);
    else if (v === '--since')   a.since   = parseSince(argv[++i]);
    else if (v === '--sort')    a.sort    = argv[++i];
    else if (v === '--all')     a.all     = true;
    else if (v === '--full-url') a.fullUrl = true;
    else if (v === '-h' || v === '--help') { printUsage(); process.exit(0); }
    else if (v.startsWith('--')) die(`未知参数: ${v}`);
    else a.keywords.push(v);
  }
  if (a.only && !['bookmarks', 'history'].includes(a.only)) die('--only 仅支持 bookmarks|history');
  if (!['recent', 'visits'].includes(a.sort)) die('--sort 仅支持 recent|visits');
  if (Number.isNaN(a.limit) || a.limit < 0) die('--limit 需为非负整数');
  return a;
}

function parseSince(s) {
  if (!s) die('--since 需要值');
  const m = s.match(/^(\d+)([dhm])$/);
  if (m) {
    const n = parseInt(m[1], 10);
    const ms = { d: 86400000, h: 3600000, m: 60000 }[m[2]];
    return new Date(Date.now() - n * ms);
  }
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) die(`无效 --since: ${s}（用 1d / 7h / 30m / YYYY-MM-DD）`);
  return d;
}

function die(msg) { console.error(msg); process.exit(1); }
function printUsage() { console.error('node find-url.mjs [关键词...] [--only bookmarks|history] [--limit N] [--since 1d|7d] [--sort recent|visits] [--browser chrome|edge] [--all] [--full-url]\n  --limit 0 表示无限制'); }

function knownBrowserDataDirs() {
  const home = os.homedir();
  const localAppData = process.env.LOCALAPPDATA || '';
  switch (os.platform()) {
    case 'darwin':
      return [
        { id: 'chrome', label: 'Chrome', dir: path.join(home, 'Library/Application Support/Google/Chrome') },
        { id: 'edge',   label: 'Edge',   dir: path.join(home, 'Library/Application Support/Microsoft Edge') },
      ];
    case 'linux':
      return [
        { id: 'chrome', label: 'Chrome', dir: path.join(home, '.config/google-chrome') },
        { id: 'edge',   label: 'Edge',   dir: path.join(home, '.config/microsoft-edge') },
      ];
    case 'win32':
      return [
        { id: 'chrome', label: 'Chrome', dir: path.join(localAppData, 'Google/Chrome/User Data') },
        { id: 'edge',   label: 'Edge',   dir: path.join(localAppData, 'Microsoft/Edge/User Data') },
      ];
    default: return [];
  }
}

function listProfiles(dataDir) {
  try {
    const state = JSON.parse(fs.readFileSync(path.join(dataDir, 'Local State'), 'utf-8'));
    const info = state?.profile?.info_cache || {};
    const list = Object.keys(info).map(dir => ({ dir, name: info[dir].name || dir }));
    if (list.length) return list;
  } catch {}
  return [{ dir: 'Default', name: 'Default' }];
}

function searchBookmarks(profileDir, profileName, browserLabel, keywords) {
  const file = path.join(profileDir, 'Bookmarks');
  if (!fs.existsSync(file)) return [];
  let data;
  try { data = JSON.parse(fs.readFileSync(file, 'utf-8')); } catch { return []; }
  if (!keywords.length) return [];

  const needles = keywords.map(k => k.toLowerCase());
  const out = [];
  function walk(node, trail) {
    if (!node) return;
    if (node.type === 'url') {
      const hay = `${node.name || ''} ${node.url || ''}`.toLowerCase();
      if (needles.every(n => hay.includes(n))) {
        out.push({ browser: browserLabel, profile: profileName, name: node.name || '', url: node.url || '', folder: trail.join(' / ') });
      }
    }
    if (Array.isArray(node.children)) {
      const sub = node.name ? [...trail, node.name] : trail;
      for (const c of node.children) walk(c, sub);
    }
  }
  for (const root of Object.values(data.roots || {})) walk(root, []);
  return out;
}

const WEBKIT_EPOCH_DIFF_US = 11644473600000000n;

function searchHistory(profileDir, profileName, browserLabel, keywords, since, limit, sort) {
  const src = path.join(profileDir, 'History');
  if (!fs.existsSync(src)) return [];
  const tmp = path.join(os.tmpdir(), `browser-history-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.sqlite`);
  try {
    fs.copyFileSync(src, tmp);
    const conds = ['last_visit_time > 0'];
    for (const kw of keywords) {
      const esc = kw.toLowerCase().replace(/'/g, "''").replace(/%/g, '\\%').replace(/_/g, '\\_');
      conds.push(`LOWER(title || ' ' || url) LIKE '%${esc}%' ESCAPE '\\'`);
    }
    if (since) {
      const webkitUs = BigInt(since.getTime()) * 1000n + WEBKIT_EPOCH_DIFF_US;
      conds.push(`last_visit_time >= ${webkitUs}`);
    }
    const limitClause = limit === 0 ? -1 : limit;
    const orderBy = sort === 'visits' ? 'visit_count DESC, last_visit_time DESC' : 'last_visit_time DESC';
    const sql = `SELECT title, url,
      datetime((last_visit_time - 11644473600000000)/1000000, 'unixepoch', 'localtime') AS visit,
      visit_count
      FROM urls WHERE ${conds.join(' AND ')}
      ORDER BY ${orderBy} LIMIT ${limitClause};`;

    const raw = execFileSync('sqlite3', ['-separator', '\t', tmp, sql], { encoding: 'utf-8', maxBuffer: 50 * 1024 * 1024 });
    return raw.trim().split('\n').filter(Boolean).map(line => {
      const [title, url, visit, visit_count] = line.split('\t');
      return { browser: browserLabel, profile: profileName, title, url, visit, visit_count: parseInt(visit_count, 10) };
    });
  } catch (e) {
    if (e.code === 'ENOENT') die('未找到 sqlite3。macOS/Linux 自带；Windows: winget install sqlite.sqlite');
    return [];
  } finally {
    try { fs.unlinkSync(tmp); } catch {}
  }
}

const clean = s => String(s ?? '').replaceAll('|', '│').trim();

function sanitizeUrl(url, full) {
  if (full) return url;
  try {
    const u = new URL(url);
    u.hash = '';
    u.search = '';
    return u.toString();
  } catch { return url; }
}

function originTag(item, showBrowser, showProfile) {
  if (showBrowser && showProfile) return '@' + clean(item.browser) + '-' + clean(item.profile);
  if (showBrowser) return '@' + clean(item.browser);
  if (showProfile) return '@' + clean(item.profile);
  return null;
}

function printBookmarks(items, showBrowser, showProfile, fullUrl) {
  console.log(`[书签] ${items.length} 条`);
  for (const b of items) {
    const segs = [clean(b.name) || '(无标题)', sanitizeUrl(clean(b.url), fullUrl)];
    if (b.folder) segs.push(clean(b.folder));
    const tag = originTag(b, showBrowser, showProfile);
    if (tag) segs.push(tag);
    console.log('  ' + segs.join(' | '));
  }
}

function printHistory(items, showBrowser, showProfile, sortLabel, fullUrl) {
  console.log(`[历史] ${items.length} 条（${sortLabel}）`);
  for (const h of items) {
    const segs = [clean(h.title) || '(无标题)', sanitizeUrl(clean(h.url), fullUrl), h.visit];
    if (h.visit_count > 1) segs.push(`visits=${h.visit_count}`);
    const tag = originTag(h, showBrowser, showProfile);
    if (tag) segs.push(tag);
    console.log('  ' + segs.join(' | '));
  }
}

// --- main ---
const args = parseArgs(process.argv.slice(2));

let browsers = knownBrowserDataDirs().filter(b => fs.existsSync(b.dir));
if (args.browser) {
  const filtered = browsers.filter(b => b.id === args.browser);
  if (!filtered.length) die(`未找到浏览器 ${args.browser}（已检测到：${browsers.map(b => b.id).join('、') || '无'}）`);
  browsers = filtered;
}
if (!browsers.length) die('未找到任何浏览器（Chrome / Edge）的用户数据目录');

const doBookmarks = args.only !== 'history';
const doHistory   = args.only !== 'bookmarks';

if (!args.keywords.length && doHistory && !args.all) {
  die('无关键词搜索历史会暴露浏览记录，请添加关键词或使用 --all 确认（默认隐藏 URL query/hash）');
}

const bookmarks = [];
const history = [];
for (const browser of browsers) {
  const profiles = listProfiles(browser.dir);
  for (const p of profiles) {
    const pDir = path.join(browser.dir, p.dir);
    if (!fs.existsSync(pDir)) continue;
    if (doBookmarks) bookmarks.push(...searchBookmarks(pDir, p.name, browser.label, args.keywords));
    if (doHistory)   history.push(...searchHistory(pDir, p.name, browser.label, args.keywords, args.since, args.limit === 0 ? 0 : args.limit * 2, args.sort));
  }
}

if (args.sort === 'visits') {
  history.sort((a, b) => (b.visit_count || 0) - (a.visit_count || 0) || (b.visit || '').localeCompare(a.visit || ''));
} else {
  history.sort((a, b) => (b.visit || '').localeCompare(a.visit || ''));
}
const bookmarksOut = args.limit === 0 ? bookmarks : bookmarks.slice(0, args.limit);
const historyOut   = args.limit === 0 ? history   : history.slice(0, args.limit);

const seenBrowsers = new Set([...bookmarksOut, ...historyOut].map(x => x.browser));
const seenProfiles = new Set([...bookmarksOut, ...historyOut].map(x => x.profile));
const showBrowser = seenBrowsers.size > 1;
const showProfile = seenProfiles.size > 1;

const sortLabel = args.sort === 'visits' ? '按访问次数' : '按最近访问';
if (doBookmarks) printBookmarks(bookmarksOut, showBrowser, showProfile, args.fullUrl);
if (doBookmarks && doHistory) console.log();
if (doHistory)   printHistory(historyOut, showBrowser, showProfile, sortLabel, args.fullUrl);

if (!args.keywords.length && doBookmarks && !doHistory) {
  console.error('\n提示：书签无时间维度，无关键词查询无意义。加关键词或 --only history');
}
if (!args.fullUrl) {
  console.error('\n提示：默认隐藏 URL query/hash，如需完整 URL 使用 --full-url');
}
