import assert from "node:assert/strict";

import { createAgentReachAdapter } from "../adapters/agent-reach.mjs";
import { classifyQuery } from "../core/classify.mjs";
import { selectProvidersByRole } from "../core/plan.mjs";

const DOCTOR_TEXT = [
  "Agent Reach 1.6.1",
  "",
  "unverified   bilibili     default       agent-reach check bilibili",
  "not_added    twitter      experimental  agent-reach add twitter",
  "not_added    xiaohongshu  optional      agent-reach add xiaohongshu",
  "unverified   youtube      default       agent-reach check youtube",
].join("\n");

const SEARCH_JSON = JSON.stringify({
  ok: true,
  channel: "bilibili",
  action: "search",
  backend: "bili-cli",
  items: [
    { title: "A", url: "https://www.bilibili.com/video/BV1", author: "up", text: "desc" },
    { title: "A duplicate", url: "https://www.bilibili.com/video/BV1" },
    { title: "B", url: "https://www.bilibili.com/video/BV2", published_at: "2026-11-01" },
  ],
  meta: { elapsedMs: 1234 },
});

const READ_JSON = JSON.stringify({
  ok: true,
  channel: "web",
  action: "read",
  items: [{ title: "Page", url: "https://example.com/a", text: "Body text" }],
});

const calls = [];
const runner = async argv => {
  calls.push(argv);
  if (argv[0] === "doctor") return { stdout: DOCTOR_TEXT };
  if (argv[0] === "read") return { stdout: READ_JSON };
  return { stdout: SEARCH_JSON };
};

const direct = {
  capabilities: async () => ({
    harness: "direct",
    level: "L3",
    providerPin: true,
    parallelSearch: true,
    structuredSources: true,
    fetch: false,
    providers: ["exa", "tavily"],
    autoOrder: ["exa", "tavily"],
    roles: { exa: ["semantic"], tavily: ["general"] },
    rankSemantics: { exa: "ranked", tavily: "ranked" },
    retrievalFamilies: { exa: "exa", tavily: "tavily" },
    metadata: { adapter: "direct" },
  }),
  search: async request => ({
    provider: request.provider,
    sources: [{ url: `https://example.com/${request.provider}` }],
  }),
};

// Capabilities: web providers stay, reach providers are probed from doctor output.
const adapter = createAgentReachAdapter({ runner, direct });
const caps = await adapter.capabilities();
assert.deepEqual(caps.providers, ["exa", "tavily", "reach-bilibili", "reach-youtube"]);
assert.equal(caps.fetch, true);
assert.deepEqual(caps.roles["reach-bilibili"], ["platform:bilibili", "china", "general", "fresh"]);
assert.equal(caps.retrievalFamilies["reach-bilibili"], "reach-bilibili");
assert.equal(caps.roles["reach-xiaohongshu"], undefined, "not_added channels stay out");
assert.deepEqual(caps.autoOrder.slice(0, 2), ["exa", "tavily"]);
assert.ok(calls.some(argv => argv[0] === "doctor"), "doctor probe should run once");

// Reach provider: mapped to the shared source shape, duplicates dropped.
const reachResult = await adapter.search({ provider: "reach-bilibili", query: "Python", limit: 5 });
assert.equal(reachResult.provider, "reach-bilibili");
assert.equal(reachResult.sources.length, 2);
assert.equal(reachResult.sources[0].snippet, "desc");
assert.equal(reachResult.sources[1].publishedAt, "2026-11-01");
assert.equal(reachResult.metadata.backend, "bili-cli");
const searchCall = calls.find(argv => argv[0] === "bilibili");
assert.deepEqual(searchCall.slice(0, 4), ["bilibili", "search", "Python", "--limit"]);

// Non-reach provider delegates to the direct adapter.
const webResult = await adapter.search({ provider: "exa", query: "x" });
assert.equal(webResult.sources[0].url, "https://example.com/exa");

// fetch reads a body through Agent Reach.
const fetched = await adapter.fetch("https://example.com/a");
assert.equal(fetched.content, "Page\n\nBody text");
assert.equal(fetched.title, "Page");

// A platform named in the query routes to that platform's channel first.
const xhsTask = classifyQuery("小红书 咖啡 推荐");
assert.ok(xhsTask.domainTags.includes("platform:xiaohongshu"));
const xhsCaps = await createAgentReachAdapter({ providers: ["reach-xiaohongshu"], runner, direct }).capabilities();
const routed = selectProvidersByRole(xhsTask, xhsCaps, { count: 3 });
assert.equal(routed[0], "reach-xiaohongshu");

// --providers restricts both halves; no web provider leaks into the run.
const onlyReach = await createAgentReachAdapter({ providers: ["reach-bilibili"], runner, direct }).capabilities();
assert.deepEqual(onlyReach.providers, ["reach-bilibili"]);
assert.deepEqual(onlyReach.autoOrder, ["reach-bilibili"]);
assert.deepEqual(Object.keys(onlyReach.roles), ["reach-bilibili"]);

// Upstream failure codes map onto fusion error types.
const failing = createAgentReachAdapter({
  providers: ["reach-xiaohongshu"],
  direct,
  runner: async argv => {
    if (argv[0] === "doctor") return { stdout: "" };
    return { stdout: JSON.stringify({ ok: false, error: { code: "NEED_LOGIN", message: "not logged in" } }) };
  },
});
await assert.rejects(
  () => failing.search({ provider: "reach-xiaohongshu", query: "咖啡" }),
  error => error.searchFusionType === "auth" && /NEED_LOGIN/.test(error.message),
);

// A missing binary degrades to web-only instead of breaking the run.
const missing = createAgentReachAdapter({
  direct,
  runner: async () => {
    const error = new Error("spawn agent-reach ENOENT");
    error.code = "ENOENT";
    throw error;
  },
});
const missingCaps = await missing.capabilities();
assert.deepEqual(missingCaps.providers, ["exa", "tavily"]);

// Platform items with text:null still fuse with an evidence snippet and a
// date derived from raw metadata (bilibili search shape, live-verified).
const META_JSON = JSON.stringify({
  ok: true,
  channel: "bilibili",
  action: "search",
  backend: "bili-cli",
  items: [{
    title: "M",
    url: "https://www.bilibili.com/video/BV9",
    author: "up",
    text: null,
    published_at: null,
    raw: { play: 261428, duration: "58:42", pubdate: 1730000000 },
  }],
});
const enriched = createAgentReachAdapter({
  providers: ["reach-bilibili"],
  direct,
  runner: async argv => {
    if (argv[0] === "doctor") return { stdout: "" };
    return { stdout: META_JSON };
  },
});
const meta = await enriched.search({ provider: "reach-bilibili", query: "x" });
assert.equal(meta.sources[0].snippet, "播放 261,428 · 时长 58:42");
assert.match(meta.sources[0].publishedAt, /^\d{4}-\d{2}-\d{2}T/);

// Error hints survive the mapping (Reach payloads carry actionable guidance).
const hinted = createAgentReachAdapter({
  providers: ["reach-bilibili"],
  direct,
  runner: async argv => {
    if (argv[0] === "doctor") return { stdout: "" };
    return { stdout: JSON.stringify({ ok: false, error: { code: "RATE_LIMITED", message: "slow down", hint: "wait 30s" } }) };
  },
});
await assert.rejects(
  () => hinted.search({ provider: "reach-bilibili", query: "x" }),
  error => error.searchFusionType === "rate_limit" && /wait 30s/.test(error.message),
);

// Real failure shape (live-verified): non-zero exit with the ok:false JSON on
// stdout — execFile rejects before parsePayload runs, so the payload must be
// recovered from error.stdout and classified, not surfaced as "Command failed".
const exited = createAgentReachAdapter({
  providers: ["reach-xiaohongshu"],
  direct,
  runner: async argv => {
    if (argv[0] === "doctor") return { stdout: "" };
    const error = new Error(`Command failed: agent-reach ${argv.join(" ")}`);
    error.code = 1;
    error.stdout = JSON.stringify({
      ok: false,
      error: { code: "NEED_SETUP", message: "opencli is paused", hint: "run `agent-reach doctor` for setup steps" },
    });
    throw error;
  },
});
await assert.rejects(
  () => exited.search({ provider: "reach-xiaohongshu", query: "x" }),
  error => error.searchFusionType === "auth" && /NEED_SETUP/.test(error.message) && /agent-reach doctor/.test(error.message),
);

// Same-channel subprocesses never overlap; other channels still run in parallel.
const events = [];
let releaseFirst;
const gate = new Promise(resolve => { releaseFirst = resolve; });
const queued = createAgentReachAdapter({
  providers: ["reach-bilibili", "reach-youtube"],
  direct,
  runner: async argv => {
    if (argv[0] === "doctor") return { stdout: DOCTOR_TEXT };
    events.push(`start:${argv[0]}`);
    if (argv[0] === "bilibili" && events.filter(event => event === "start:bilibili").length === 1) await gate;
    events.push(`end:${argv[0]}`);
    return { stdout: SEARCH_JSON };
  },
});
const firstBili = queued.search({ provider: "reach-bilibili", query: "a" });
const secondBili = queued.search({ provider: "reach-bilibili", query: "b" });
const youTube = queued.search({ provider: "reach-youtube", query: "c" });
await new Promise(resolve => setImmediate(resolve));
assert.deepEqual(
  events,
  ["start:bilibili", "start:youtube", "end:youtube"],
  "second same-channel call must wait for the first; other channels proceed",
);
releaseFirst();
await Promise.all([firstBili, secondBili, youTube]);
assert.equal(events.filter(event => event === "start:bilibili").length, 2);
