import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { mkdtempSync } from "node:fs";
import os from "node:os";

import { decomposeQuery } from "../core/decompose.mjs";
import { parseArgs, runSearchFusion } from "../scripts/search-fusion.mjs";
import { SEARCH_FUSION_VERSION } from "../core/version.mjs";

// Adapter-mode runs persist provider stats and cache under SEARCH_FUSION_HOME;
// isolate them so test results never depend on (or pollute) the real user state.
process.env.SEARCH_FUSION_HOME = mkdtempSync(path.join(os.tmpdir(), "sf-leaderboard-"));

const here = fileURLToPath(new URL(".", import.meta.url));

// 1. maxSubqueries is a true hard cap, base included (review P0-2).
const cmpTask = { task: "comparison", freshness: "recent", domain: "coding", domainTags: ["coding"], depth: "deep" };
assert.equal(decomposeQuery("横评 Exa 和 Tavily 的最新搜索能力", cmpTask, 1).length, 1);
assert.equal(decomposeQuery("横评 Exa 和 Tavily 的最新搜索能力", cmpTask, 2).length, 2);
assert.equal(decomposeQuery("横评 Exa 和 Tavily 的最新搜索能力", cmpTask, 3).length, 3);

// 2. --plan without capabilities emits provider-agnostic intents (review P0-1).
const plan = await runSearchFusion("横评 Exa 和 Tavily 的最新搜索能力", { plan: true });
assert.equal(plan.providerAgnostic, true);
assert.ok(plan.requests.length >= 3);
assert.equal(plan.requests[0].provider, null);
assert.ok(plan.requests.every(request => request.query && request.id && request.wave));
assert.equal(plan.runManifest.searchFusionVersion, SEARCH_FUSION_VERSION);

// 3. Benchmark profile parsing and search-api defaults (review P0-3).
const profiled = parseArgs(["--benchmark-profile", "search-api", "--input", "f.json", "q"]);
assert.equal(profiled.options.benchmarkProfile, "search-api");
assert.throws(() => parseArgs(["--benchmark-profile", "bogus", "--input", "f.json", "q"]), /--benchmark-profile must be one of/);

// 4. Fixtures are canonical envelopes (review P0.5).
for (const name of ["host-results.json", "alpha-stale.json"]) {
  const fixture = JSON.parse(readFileSync(path.join(here, "fixtures", name), "utf8"));
  assert.equal(fixture.schemaVersion, 1, `${name} schemaVersion`);
  assert.equal(typeof fixture.query, "string", `${name} query`);
  assert.ok(Array.isArray(fixture.attempts), `${name} attempts`);
}

// 5. Manifest carries version, config digests and underlying call accounting.
const hostFixture = path.join(here, "fixtures", "host-results.json");
const fused = await runSearchFusion("current OpenAI API documentation", { input: hostFixture, top: 8 });
assert.equal(fused.runManifest.searchFusionVersion, SEARCH_FUSION_VERSION);
assert.equal(fused.runManifest.schemaVersion, 1);
assert.equal(typeof fused.runManifest.configDigests.providerDefaults, "string");
assert.equal(typeof fused.runManifest.configDigests.sourceProvenance, "string");
assert.equal(fused.runManifest.cost.budgetUnit, "underlying-search-call");
assert.equal(fused.runManifest.cost.underlyingSearchCalls, 2);
assert.deepEqual(fused.runManifest.cost.providerCalls, { exa: 1, gemini: 1 });

// 6. search-api profile: strict pin rejects provider mismatch (review P1).
process.env.OMP_SEARCH_MODULE = path.join(here, "fixtures", "mock-omp-module.mjs");
const strictRun = await runSearchFusion("normal typescript api query", {
  adapter: "omp",
  benchmarkProfile: "search-api",
  depth: "quick",
  providerCount: 1,
  maxSubqueries: 1,
  timeoutMs: 20_000,
});
assert.equal(strictRun.budget.maxFallbackCalls, 0);
assert.equal(strictRun.budget.maxSearchCalls, 5);
assert.ok(strictRun.providers.failures.some(failure => failure.errorType === "provider_mismatch"));
assert.equal(strictRun.providers.used.length, 0);

// 7. Same request without strict pin accepts the OMP-internal fallback.
const lenient = await runSearchFusion("normal typescript api query", {
  adapter: "omp",
  depth: "quick",
  providerCount: 1,
  maxSubqueries: 1,
  maxFallbackCalls: 0,
  timeoutMs: 20_000,
});
assert.equal(lenient.providers.used.length, 1);
assert.equal(lenient.providers.used[0], "gemini");
assert.equal(lenient.attempts[0].requestedProvider, "exa");

console.log("search-fusion leaderboard checks passed");
