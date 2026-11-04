// Composite adapter: direct web providers + Agent Reach platform channels.
//
// Agent Reach is read-only and returns platform-native results (Bilibili,
// Xiaohongshu, YouTube, X). Search Fusion keeps owning discovery, fusion and
// provenance; this adapter only turns `agent-reach <channel> search` into the
// shared SearchResponse contract, and delegates every other provider to the
// direct adapter so web evidence and platform evidence fuse together.
import { execFile } from "node:child_process";
import path from "node:path";

import { createDirectAdapter } from "./direct.mjs";

const DEFAULT_REACH_PROVIDERS = ["reach-bilibili", "reach-xiaohongshu", "reach-youtube"];

const REACH_CHANNELS = {
  "reach-bilibili": { channel: "bilibili", action: "search" },
  "reach-xiaohongshu": { channel: "xiaohongshu", action: "search" },
  "reach-youtube": { channel: "youtube", action: "search" },
  "reach-twitter": { channel: "twitter", action: "search" },
};

const REACH_ROLES = {
  "reach-bilibili": ["platform:bilibili", "china", "general", "fresh"],
  "reach-xiaohongshu": ["platform:xiaohongshu", "china", "general", "fresh"],
  "reach-youtube": ["platform:youtube", "general", "fresh"],
  "reach-twitter": ["platform:twitter", "general", "fresh"],
};

const REACH_TIMEOUT_MS = 60000;
const PROBE_TIMEOUT_MS = 15000;

function reachBinary(env = process.env) {
  if (env.AGENT_REACH_BIN) return env.AGENT_REACH_BIN;
  if (process.platform === "win32") {
    const home = env.USERPROFILE || env.HOME;
    if (home) return path.join(home, ".local", "bin", "agent-reach.exe");
  }
  return "agent-reach";
}

function childEnv() {
  // Agent Reach prints UTF-8 JSON; keep the child from inheriting a legacy code page.
  return { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8" };
}

function runDefault(bin, argv, { timeoutMs, signal } = {}) {
  return new Promise((resolve, reject) => {
    execFile(
      bin,
      argv,
      { timeout: timeoutMs, signal, windowsHide: true, maxBuffer: 16 * 1024 * 1024, env: childEnv() },
      (error, stdout, stderr) => {
        if (error) {
          error.stdout = stdout;
          error.stderr = stderr;
          reject(error);
          return;
        }
        resolve({ stdout, stderr });
      },
    );
  });
}

function mapReachError(error) {
  const code = error?.code ?? "UPSTREAM_BROKEN";
  const parts = [error?.message ?? "Agent Reach failed"];
  // Reach error payloads carry an actionable hint (e.g. "wait retry_after_seconds"); keep it.
  if (error?.hint) parts.push(error.hint);
  const mapped = new Error(`${code}: ${parts.join(" — ")}`);
  if (code === "NEED_LOGIN" || code === "NEED_SETUP") mapped.searchFusionType = "auth";
  else if (code === "RATE_LIMITED") mapped.searchFusionType = "rate_limit";
  else if (code === "TIMEOUT" || code === "BUSY") mapped.searchFusionType = "timeout";
  else mapped.searchFusionType = "provider";
  return mapped;
}

function parsePayload(stdout) {
  const text = String(stdout ?? "").trim();
  if (!text) {
    const err = new Error("Agent Reach returned no output");
    err.searchFusionType = "provider";
    throw err;
  }
  const candidates = [text];
  // Tolerate a human-readable prefix: take the last line that starts with "{".
  const lastBraceLine = text.split(/\r?\n/).reverse().find(line => line.trim().startsWith("{"));
  if (lastBraceLine && lastBraceLine !== text) candidates.push(lastBraceLine.trim());
  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch {
      // try the next candidate
    }
  }
  const err = new Error("Agent Reach output was not JSON");
  err.searchFusionType = "provider";
  throw err;
}

// Platform search items often return text:null but carry structured raw fields
// (bilibili: play/duration; youtube/twitter: view/publish metadata). Derive a
// compact evidence snippet so platform sources do not fuse as title-only.
const RAW_DATE_FIELDS = ["pubdate", "publish_time", "published_at", "publishedAt", "publishedTimeText", "created_at", "createdAt", "created"];

function rawDateString(raw = {}) {
  for (const field of RAW_DATE_FIELDS) {
    const value = raw[field];
    if (typeof value === "string" && value.trim() && Number.isNaN(Date.parse(value)) === false) return value;
    if (typeof value === "number" && value > 0) return new Date(value * (value < 1e12 ? 1000 : 1)).toISOString();
  }
  return null;
}

function rawMetaSnippet(raw = {}) {
  const bits = [];
  const views = raw.play ?? raw.view_count ?? raw.viewCount ?? raw.views;
  if (Number.isFinite(Number(views)) && Number(views) >= 0) bits.push(`播放 ${Number(views).toLocaleString("en-US")}`);
  const duration = raw.duration ?? raw.duration_text ?? raw.durationText;
  if (typeof duration === "string" && /^\d{1,3}(:\d{2}){1,2}$/.test(duration)) bits.push(`时长 ${duration}`);
  return bits.length ? bits.join(" · ") : null;
}

function toSources(items) {
  const seen = new Set();
  const sources = [];
  for (const item of items ?? []) {
    const url = typeof item?.url === "string" ? item.url.trim() : "";
    if (!url || seen.has(url)) continue;
    seen.add(url);
    const source = { url };
    if (item.title) source.title = String(item.title);
    const snippet = item.text ?? item.raw?.description ?? item.raw?.snippet ?? rawMetaSnippet(item.raw ?? {});
    if (snippet) source.snippet = String(snippet).slice(0, 1200);
    const publishedAt = item.published_at ?? rawDateString(item.raw ?? {});
    if (publishedAt) source.publishedAt = String(publishedAt);
    if (item.author) source.author = String(item.author);
    sources.push(source);
  }
  return sources;
}

// Agent Reach reports failures as a NON-ZERO exit with a valid ok:false JSON
// still on stdout (live-verified: NEED_SETUP/NEED_LOGIN exit 1, stderr empty).
// execFile rejects on non-zero exit, so recover the payload from error.stdout.
function payloadFromSpawnError(error) {
  if (!error?.stdout) return null;
  try {
    const payload = parsePayload(error.stdout);
    return payload?.ok === false ? payload : null;
  } catch {
    return null;
  }
}

function probeAvailableChannels(stdout) {
  // `doctor --text` is offline; `not_added` rows are channels that were never installed.
  const available = new Set();
  for (const line of String(stdout ?? "").split(/\r?\n/)) {
    const match = line.match(/^\s*(not_added|unverified|needs_setup|needs_login|ready|ok)\s+(\S+)/);
    if (!match) continue;
    if (match[1] === "not_added") continue;
    available.add(match[2]);
  }
  return available;
}

export function createAgentReachAdapter({
  providers,
  env = process.env,
  bin = reachBinary(env),
  runner,
  direct,
  authMode = "auto",
} = {}) {
  const requested = providers?.length ? [...new Set(providers)] : null;
  const reachCandidates = (requested ?? DEFAULT_REACH_PROVIDERS).filter(id => REACH_CHANNELS[id]);
  const directAdapter = direct ?? createDirectAdapter({ env, authMode });
  const run = runner
    ? (argv, options) => runner(argv, options)
    : (argv, options) => runDefault(bin, argv, options);
  let probe;

  // Agent Reach enforces per-platform limits (max 2 concurrent, >=10s between
  // two searches on one platform, max 4 in flight overall) by queueing for up
  // to 2 minutes. Fusion waves fire same-channel calls in parallel via
  // Promise.all, which would lean on that queue and can outlive our 60s
  // subprocess timeout. Serialize per channel in-process instead: one
  // in-flight subprocess per platform, queued callers start as soon as the
  // previous one settles (Reach applies its own spacing).
  const channelTails = new Map();
  function enqueueChannel(channel, task, signal) {
    const tail = channelTails.get(channel) ?? Promise.resolve();
    const run = tail.then(
      () => {
        if (signal?.aborted) {
          const aborted = new Error(`${channel} call aborted while queued`);
          aborted.searchFusionType = "timeout";
          return Promise.reject(aborted);
        }
        return task();
      },
      () => task(),
    );
    channelTails.set(channel, run.catch(() => {}));
    return run;
  }

  async function availableReachProviders() {
    if (probe) return probe;
    if (requested) {
      probe = reachCandidates;
      return probe;
    }
    try {
      const { stdout } = await run(["doctor", "--text"], { timeoutMs: PROBE_TIMEOUT_MS });
      const installed = probeAvailableChannels(stdout);
      probe = reachCandidates.filter(id => installed.has(REACH_CHANNELS[id].channel));
    } catch {
      probe = [];
    }
    return probe;
  }

  async function reachSearch(request) {
    const spec = REACH_CHANNELS[request.provider];
    const limit = Number.isFinite(request.limit) ? Math.max(1, Math.min(20, request.limit)) : 6;
    const timeoutMs = Math.max(REACH_TIMEOUT_MS, Number(request.timeoutMs) || 0);
    let payload;
    try {
      const { stdout } = await enqueueChannel(
        spec.channel,
        () => run([spec.channel, spec.action, request.query, "--limit", String(limit)], { timeoutMs, signal: request.signal }),
        request.signal,
      );
      payload = parsePayload(stdout);
    } catch (error) {
      if (error?.searchFusionType) throw error;
      const failure = payloadFromSpawnError(error);
      if (failure) throw mapReachError(failure.error);
      if (error?.killed || error?.name === "AbortError" || /timed? ?out/i.test(error?.message ?? "")) {
        const timeout = new Error(`${request.provider} timed out`);
        timeout.searchFusionType = "timeout";
        throw timeout;
      }
      if (error?.code === "ENOENT") {
        const missing = new Error("agent-reach is not installed or not on PATH");
        missing.searchFusionType = "auth";
        throw missing;
      }
      throw error;
    }
    if (!payload?.ok) throw mapReachError(payload?.error);
    return {
      provider: request.provider,
      sources: toSources(payload.items),
      searchQueries: [request.query],
      metadata: {
        channel: spec.channel,
        action: spec.action,
        backend: payload.backend ?? null,
        elapsedMs: payload.meta?.elapsedMs ?? null,
      },
    };
  }

  async function reachFetch(url) {
    let payload;
    try {
      const { stdout } = await run(["read", url], { timeoutMs: REACH_TIMEOUT_MS });
      payload = parsePayload(stdout);
    } catch (error) {
      if (error?.searchFusionType) throw error;
      const failure = payloadFromSpawnError(error);
      if (failure) throw mapReachError(failure.error);
      throw mapReachError({ code: "UPSTREAM_BROKEN", message: error?.message ?? "read failed" });
    }
    if (!payload?.ok) throw mapReachError(payload?.error);
    const items = payload.items ?? [];
    const content = items
      .map(item => [item.title, item.text].filter(Boolean).join("\n\n"))
      .filter(Boolean)
      .join("\n\n---\n\n");
    if (!content) {
      const empty = new Error("Agent Reach returned no readable body");
      empty.searchFusionType = "provider";
      throw empty;
    }
    return { url, title: items[0]?.title, content, contentType: "text/plain" };
  }

  return {
    name: "reach",
    capabilities: async () => {
      const base = await directAdapter.capabilities();
      const reach = await availableReachProviders();
      // --providers restricts both halves; the direct adapter cannot express
      // "no web providers", so filter its capability view here.
      const webProviders = requested
        ? base.providers.filter(id => requested.includes(id))
        : base.providers;
      const providers = [...webProviders, ...reach];
      const keep = new Set(providers);
      const pick = map => Object.fromEntries(Object.entries(map).filter(([id]) => keep.has(id)));
      const roles = pick({ ...base.roles });
      const rankSemantics = pick({ ...base.rankSemantics });
      const retrievalFamilies = pick({ ...base.retrievalFamilies });
      for (const id of reach) {
        roles[id] = [...REACH_ROLES[id]];
        rankSemantics[id] = "ranked";
        retrievalFamilies[id] = id;
      }
      return {
        ...base,
        providers,
        roles,
        rankSemantics,
        retrievalFamilies,
        // Platform sources break ties after web providers; role matching still wins.
        autoOrder: [...base.autoOrder.filter(id => keep.has(id)), ...reach],
        fetch: true,
        metadata: { ...base.metadata, adapter: "reach", reachProviders: reach },
      };
    },
    search: async request => {
      if (REACH_CHANNELS[request.provider]) return reachSearch(request);
      return directAdapter.search(request);
    },
    fetch: async url => {
      if (!/^https?:\/\//i.test(String(url))) {
        const err = new Error("only http(s) URLs can be read");
        err.searchFusionType = "type";
        throw err;
      }
      return reachFetch(url);
    },
  };
}
