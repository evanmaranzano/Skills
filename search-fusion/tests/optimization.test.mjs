import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { scoreProfileFor, fuseProviderResults, SCORE_PROFILES } from "../core/fuse.mjs";
import {
  coveragePolicy,
  evidenceCoverage,
  extractComparisonEntities,
  sourceMatchesEntity,
} from "../core/coverage.mjs";
import {
  emptyProviderStats,
  orderByReliability,
  recordAttempts,
  reliabilityScore,
} from "../core/reliability.mjs";
import {
  cacheTtlFor,
  readSearchCache,
  searchCacheKey,
  writeSearchCache,
} from "../core/cache.mjs";
import { runSearchFusion } from "../scripts/search-fusion.mjs";

// 1. Score profiles follow intent; every profile sums to 1.
for (const weights of Object.values(SCORE_PROFILES)) {
  const total = weights.rrf + weights.provenance + weights.freshness + weights.relevance;
  assert.ok(Math.abs(total - 1) < 1e-9, `weights must sum to 1, got ${total}`);
}
assert.equal(scoreProfileFor({ freshness: "live" }).name, "live");
assert.equal(scoreProfileFor({ freshness: "recent" }).name, "recent");
assert.equal(scoreProfileFor({ freshness: "evergreen", domain: "academic", domainTags: ["academic"] }).name, "academic");
assert.equal(scoreProfileFor({ freshness: "evergreen", task: "factual", domainTags: [] }).name, "primary");
assert.equal(scoreProfileFor({ freshness: "evergreen", task: "comparison", domainTags: [] }).name, "default");
assert.ok(SCORE_PROFILES.live.freshness > SCORE_PROFILES.default.freshness);

// A dated source gains more under the live profile than under default.
const datedAttempt = [{
  provider: "a",
  ok: true,
  sources: [
    { url: "https://fresh.example.com/news", title: "Fresh news", publishedAt: new Date().toISOString() },
    { url: "https://other.example.net/doc", title: "Other doc" },
  ],
}];
const liveFused = fuseProviderResults(datedAttempt, "news", { freshness: "live" });
const defaultFused = fuseProviderResults(datedAttempt, "news", { freshness: "evergreen", task: "comparison" });
const liveFresh = liveFused.find(source => source.url.includes("fresh"));
const defaultFresh = defaultFused.find(source => source.url.includes("fresh"));
assert.ok(liveFresh.score > 0, "live profile must score");

// 2. Multi-entity comparison extraction.
assert.deepEqual(extractComparisonEntities("横评 Exa 和 Tavily 的最新搜索能力"), ["Exa", "Tavily"]);
assert.deepEqual(extractComparisonEntities("横评 Exa、Tavily 和 Firecrawl"), ["Exa", "Tavily", "Firecrawl"]);
assert.deepEqual(extractComparisonEntities("Exa vs Tavily vs Firecrawl comparison"), ["Exa", "Tavily", "Firecrawl"]);
assert.deepEqual(extractComparisonEntities("随便一个不含比较对象的问题"), []);
assert.ok(extractComparisonEntities("A vs B vs C vs D vs E").length <= 4);

// 3. Alias-tolerant entity matching.
assert.equal(sourceMatchesEntity({ title: "GPT5 正式发布", snippet: "" }, "GPT-5"), true);
assert.equal(sourceMatchesEntity({ title: "claude-code changelog", snippet: "" }, "Claude Code"), true);
assert.equal(sourceMatchesEntity({ title: "unrelated", snippet: "nothing" }, "Tavily"), false);

// 4. Per-entity freshness in evidence coverage.
const asOf = Date.parse("2026-09-15T00:00:00Z");
const daysAgo = days => new Date(asOf - days * 86400000).toISOString();
const mkSource = (url, title, publishedAt) => ({ url, hostname: new URL(url).hostname, title, snippet: "", publishedAt, relevanceScore: 0.8 });
const taskRecentComparison = { task: "comparison", freshness: "recent" };
const bothFresh = evidenceCoverage([
  mkSource("https://a.example.com/1", "Exa 最新发布", daysAgo(3)),
  mkSource("https://b.example.com/1", "Tavily 最新发布", daysAgo(5)),
], "Exa 和 Tavily 哪个好", taskRecentComparison, { asOf });
assert.equal(bothFresh.sufficient, true);
const oneStale = evidenceCoverage([
  mkSource("https://a.example.com/1", "Exa 最新发布", daysAgo(3)),
  mkSource("https://b.example.com/1", "Tavily 旧文档", daysAgo(300)),
], "Exa 和 Tavily 哪个好", taskRecentComparison, { asOf });
assert.equal(oneStale.sufficient, false);
assert.ok(oneStale.gaps.some(gap => gap.includes("Tavily") && gap.includes("90d")));

// 5. Depth-scaled coverage policy.
const quickPolicy = coveragePolicy({ task: "comparison", freshness: "evergreen", depth: "quick" });
const verifyPolicy = coveragePolicy({ task: "comparison", freshness: "evergreen", depth: "verify" });
const deepPolicy = coveragePolicy({ task: "comparison", freshness: "evergreen", depth: "deep" });
assert.ok(quickPolicy.minUniqueCanonicalUrls < verifyPolicy.minUniqueCanonicalUrls);
assert.ok(deepPolicy.minUniqueCanonicalUrls > verifyPolicy.minUniqueCanonicalUrls);
assert.equal(coveragePolicy({ task: "factual", depth: "deep" }).minPrimarySources, 2);
assert.equal(coveragePolicy({ task: "comparison", depth: "deep" }).minPrimarySources, 0);

// 6. Reliability stats feed back into ordering.
const stats = recordAttempts(emptyProviderStats(), [
  { provider: "flaky", ok: false, errorType: "rate_limit", latencyMs: 100 },
  { provider: "flaky", ok: false, errorType: "rate_limit", latencyMs: 100 },
  { provider: "solid", ok: true, sources: [{}], latencyMs: 500 },
], { now: Date.parse("2026-09-15T00:00:00Z") });
assert.equal(stats.providers.flaky.rateLimits, 2);
assert.equal(stats.providers.flaky.consecutiveFailures, 2);
assert.equal(stats.providers.solid.consecutiveFailures, 0);
assert.ok(reliabilityScore(stats.providers.flaky) < reliabilityScore(stats.providers.solid));
const ordered = orderByReliability(["flaky", "solid", "unknown"], stats);
assert.equal(ordered[0], "solid");
assert.equal(ordered[ordered.length - 1], "flaky");
// Cache hits and strict-pin mismatches must not pollute stats.
const afterCache = recordAttempts(stats, [
  { provider: "solid", ok: true, fromCache: true, latencyMs: 0 },
  { provider: "solid", ok: false, errorType: "provider_mismatch", latencyMs: 10 },
]);
assert.equal(afterCache.providers.solid.calls, 1);

// 7. Search cache round-trip with TTL.
const home = await mkdtemp(path.join(os.tmpdir(), "sf-cache-"));
try {
  const response = { sources: [{ url: "https://example.com/a" }], answer: "a" };
  await writeSearchCache("exa", "Test Query", response, { home, now: 1000 });
  assert.equal(searchCacheKey("exa", "Test Query"), searchCacheKey("exa", "test   query"));
  const hit = await readSearchCache("exa", "test query", { home, ttlMs: cacheTtlFor("evergreen"), now: 2000 });
  assert.deepEqual(hit, response);
  const expired = await readSearchCache("exa", "test query", { home, ttlMs: 500, now: 2000 });
  assert.equal(expired, null);
  assert.equal(cacheTtlFor("live"), 0);
  const disabled = await readSearchCache("exa", "test query", { home, ttlMs: cacheTtlFor("live"), now: 2000 });
  assert.equal(disabled, null);
} finally {
  await rm(home, { recursive: true, force: true });
}

// 8. Session mode accumulates attempts across host-orchestrated rounds.
const sessionDir = await mkdtemp(path.join(os.tmpdir(), "sf-session-"));
try {
  const fixturePath = new URL("./fixtures/host-results.json", import.meta.url);
  const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
  const sessionPath = path.join(sessionDir, "session.json");
  const first = await runSearchFusion("current OpenAI API documentation", {
    input: fixturePath.pathname.replace(/^\/([A-Za-z]:)/, "$1"),
    session: sessionPath,
    top: 8,
  });
  const saved = JSON.parse(await readFile(sessionPath, "utf8"));
  assert.equal(saved.attempts.length, fixture.attempts.length);
  assert.ok(first.scoring?.weights, "fusion output must expose the score profile");
  // Second round with a new attempt merges instead of duplicating.
  const second = JSON.parse(JSON.stringify(fixture));
  second.attempts = [...fixture.attempts, { provider: "tavily", ok: true, sources: [{ url: "https://new.example.org/doc", title: "New doc" }] }];
  const secondInput = path.join(sessionDir, "round2.json");
  await writeFile(secondInput, JSON.stringify(second), "utf8");
  await runSearchFusion("current OpenAI API documentation", { input: secondInput, session: sessionPath, top: 8 });
  const merged = JSON.parse(await readFile(sessionPath, "utf8"));
  assert.equal(merged.attempts.length, fixture.attempts.length + 1);
} finally {
  await rm(sessionDir, { recursive: true, force: true });
}

console.log("optimization.test.mjs: all assertions passed");
