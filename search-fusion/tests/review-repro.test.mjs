import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { fuseProviderResults, freshnessScore } from "../core/fuse.mjs";
import { combinedCoverage } from "../core/coverage.mjs";
import { classifyProvenance } from "../core/provenance.mjs";
import { looseCanonicalUrl } from "../core/normalize.mjs";
import { parseArgs, runSearchFusion, withTimeout } from "../scripts/search-fusion.mjs";

const here = fileURLToPath(new URL(".", import.meta.url));
const alphaFixture = path.join(here, "fixtures", "alpha-stale.json");
const hostFixture = path.join(here, "fixtures", "host-results.json");

// 1. Failed attempts must not contribute RRF or support (review §4).
const polluted = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a", title: "q" }] },
  { provider: "gemini", ok: false, error: "boom", sources: [{ url: "https://example.com/a", title: "q" }] },
], "q", { freshness: "evergreen" }, { rankSemantics: { exa: "ranked", gemini: "citation-order" } });
assert.equal(polluted[0].providerSupport, 1);
assert.equal(polluted[0].providerSupportRatio, 1);

// 2. Six stale single-entity pages must not satisfy a comparison (review §1).
const stale = await runSearchFusion("Alpha vs Beta latest comparison", { input: alphaFixture, top: 8 });
assert.equal(stale.coverage.sufficient, false);
assert.ok(stale.coverage.gaps.some(gap => gap.includes("Beta")));
assert.ok(stale.coverage.gaps.some(gap => gap.includes("window")));
assert.equal(stale.stopReason, "budget-exhausted");

// 3. --next emits concrete remaining requests for the gaps.
const next = await runSearchFusion("Alpha vs Beta latest comparison", { input: alphaFixture, next: true });
assert.equal(next.action, "next");
assert.ok(next.requests.length > 0);
assert.ok(next.gaps.length > 0);

// 4. Future dates are penalized, not rewarded (review §11).
const future = freshnessScore({ publishedAt: "2999-01-01" }, "recent", Date.parse("2026-09-14"));
assert.ok(future <= 0.3);

// 5. ageSeconds=0 survives merging with an older observation (review §11).
const merged = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a", title: "q", ageSeconds: 0 }] },
  { provider: "gemini", ok: true, sources: [{ url: "https://example.com/a", title: "q", ageSeconds: 864_000 }] },
], "q", { freshness: "evergreen" });
assert.equal(merged[0].ageSeconds, 0);

// 6. Input order does not change merged date or score (review §11).
const asOf = Date.parse("2026-09-14");
const orderA = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a", title: "q", publishedAt: "2026-01-01" }] },
  { provider: "gemini", ok: true, sources: [{ url: "https://example.com/a", title: "q", publishedAt: "2026-06-01" }] },
], "q", { freshness: "recent", asOf });
const orderB = fuseProviderResults([
  { provider: "gemini", ok: true, sources: [{ url: "https://example.com/a", title: "q", publishedAt: "2026-06-01" }] },
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a", title: "q", publishedAt: "2026-01-01" }] },
], "q", { freshness: "recent", asOf });
assert.equal(orderA[0].publishedAt, orderB[0].publishedAt);
assert.equal(orderA[0].score, orderB[0].score);

// 7. Provenance: community subdomains and query-param hints (review §5).
assert.equal(classifyProvenance("https://community.openai.com/t/some-post"), "community");
assert.equal(classifyProvenance("https://random-blog.example.com/post?tag=benchmark"), "unknown");

// 8. SPA hash routes stay distinct; junk fragments merge (review §12).
assert.notEqual(
  looseCanonicalUrl("https://example.com/#/product-a"),
  looseCanonicalUrl("https://example.com/#/product-b"),
);
assert.equal(
  looseCanonicalUrl("https://example.com/page#section-1"),
  looseCanonicalUrl("https://example.com/page#section-2"),
);

// 9. CLI validation: numeric coercion and enum rejection (review §10).
assert.equal(parseArgs(["--input", "f.json", "--top=8", "q"]).options.top, 8);
assert.throws(() => parseArgs(["--input", "f.json", "--depth", "invalid", "q"]), /--depth must be one of/);

// 10. Fast/slow timeout keeps fast results and marks partial (review §2).
const tmp = mkdtempSync(path.join(tmpdir(), "sf-caps-"));
const capsFile = path.join(tmp, "capabilities.json");
writeFileSync(capsFile, JSON.stringify({
  adapter: path.join(here, "fixtures", "mock-adapter.mjs"),
  harness: "mock",
  providerPin: true,
  parallelSearch: true,
  structuredSources: true,
  providers: ["fast", "slow"],
  autoOrder: ["fast", "slow"],
  roles: { fast: ["general"], slow: ["general"] },
  rankSemantics: { fast: "ranked", slow: "ranked" },
  retrievalFamilies: { fast: "fast", slow: "slow" },
}), "utf8");
const timeoutRun = await runSearchFusion("alpha beta", { capabilities: capsFile, timeoutMs: 1_500, top: 4 });
assert.equal(timeoutRun.status, "partial");
assert.equal(timeoutRun.stopReason, "deadline");
assert.ok(timeoutRun.results.some(source => source.url.includes("fast.example.com")));
assert.ok(timeoutRun.providers.failures.some(failure => failure.provider === "slow" && failure.errorType === "timeout"));

// 11. Hanging capabilities are bounded by the deadline (review §2).
await assert.rejects(
  withTimeout(new Promise(() => {}), 50),
  /deadline exceeded/,
);

// 12. OMP adapter: structured error and provider identity (review §3).
process.env.OMP_SEARCH_MODULE = path.join(here, "fixtures", "mock-omp-module.mjs");
const { createOmpInternalAdapter } = await import("../adapters/omp-internal.mjs");
const omp = createOmpInternalAdapter();
await assert.rejects(
  omp.search({ query: "fail-auth", provider: "exa" }),
  error => error.searchFusionType === "auth" && /401/.test(error.message),
);
const rerouted = await omp.search({ query: "normal query", provider: "exa" });
assert.equal(rerouted.provider, "gemini");
assert.equal(rerouted.requestedProvider, "exa");
const emptyOk = await omp.search({ query: "empty-ok", provider: "exa" });
assert.deepEqual(emptyOk.sources, []);
const ompCaps = await omp.capabilities();
assert.ok(ompCaps.providers.length > 5);
assert.ok(ompCaps.metadata.availableProviders.length >= ompCaps.providers.length);

// 13. --plan emits requests without executing (review §9).
const plan = await runSearchFusion("横评 Exa 和 Tavily 的最新搜索能力", { plan: true });
assert.equal(plan.action, "plan");
assert.ok(plan.facets.some(facet => facet.entities?.includes("Exa")));
assert.ok(plan.facets.some(facet => facet.entities?.includes("Tavily")));

// 14. Equivalent input fuses identically in host mode (review §4 acceptance).
const hostA = await runSearchFusion("current OpenAI API documentation", { input: hostFixture, top: 8, asOf: "2026-09-14" });
const hostB = await runSearchFusion("current OpenAI API documentation", { input: hostFixture, top: 8, asOf: "2026-09-14" });
assert.deepEqual(hostA.results.map(source => source.url), hostB.results.map(source => source.url));

// 15. combinedCoverage exposes retrieval vs evidence separately (review §1).
const combined = combinedCoverage(
  [{ url: "https://example.com/a", hostname: "example.com", relevanceScore: 0.5, families: ["exa"], provenance: "unknown" }],
  [{ provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] }],
  "q",
  { task: "factual", freshness: "evergreen" },
);
assert.ok("retrieval" in combined && "evidence" in combined);
assert.equal(combined.sufficient, false);

console.log("search-fusion review-repro checks passed");
