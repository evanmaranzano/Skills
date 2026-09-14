import assert from "node:assert/strict";
import { classifyQuery } from "../core/classify.mjs";
import { decomposeQuery } from "../core/decompose.mjs";
import { normalizeUrl } from "../core/normalize.mjs";
import { fuseProviderResults } from "../core/fuse.mjs";
import { diversifySources } from "../core/rerank.mjs";
import { retrievalCoverage, evidenceCoverage, combinedCoverage, extractComparisonEntities } from "../core/coverage.mjs";
import { planFusion, normalizeCapabilities, mapSearchCalls, selectProvidersByRole } from "../core/plan.mjs";

const intent = classifyQuery("横评 Exa 和 Tavily 的最新搜索能力");
assert.equal(intent.task, "comparison");
assert.equal(intent.freshness, "recent");
assert.equal(intent.domain, "coding");
assert.equal(intent.depth, "deep");

const variants = decomposeQuery("Exa vs Tavily search quality", intent, 3);
assert.ok(variants.length >= 2 && variants.length <= 3);
assert.equal(variants[0].id, "base");
assert.ok(variants[0].query);
assert.ok(variants.some(facet => facet.required));

assert.deepEqual(extractComparisonEntities("横评 Exa 和 Tavily 的最新搜索能力"), ["Exa", "Tavily"]);

assert.equal(
  normalizeUrl("https://www.example.com/a/?utm_source=test&ref=abc&b=2#part"),
  "https://example.com/a?b=2&ref=abc",
);

const fused = fuseProviderResults(
  [
    {
      provider: "exa",
      sources: [
        { title: "Official docs", url: "https://developers.openai.com/api/docs?utm_source=exa", snippet: "Current API documentation", publishedAt: "2026-09-01" },
        { title: "Blog result", url: "https://example.com/blog/openai-api", snippet: "Secondary notes" },
      ],
    },
    {
      provider: "gemini",
      sources: [
        { title: "Official docs mirror", url: "https://developers.openai.com/api/docs", snippet: "Current API documentation with details", publishedAt: "2026-09-02" },
      ],
    },
  ],
  "current OpenAI API documentation",
  { freshness: "recent" },
  { rankSemantics: { exa: "ranked", gemini: "citation-order" } },
);

assert.equal(fused.length, 2);
assert.equal(fused[0].url, "https://developers.openai.com/api/docs");
assert.equal(fused[0].provenance, "primary_official");
assert.equal(fused[0].providerSupport, 2);
assert.ok(fused[0].score > fused[1].score);

const diverse = diversifySources([
  ...fused,
  { url: "https://developers.openai.com/api/other", hostname: "developers.openai.com", title: "Other", score: 0.9, provenance: "primary_official" },
], { top: 3, perDomain: 1 });
assert.equal(diverse.length, 2);
assert.equal(new Set(diverse.map(source => source.hostname)).size, 2);

const coverage = retrievalCoverage(fused, [
  { provider: "exa", ok: true, sources: [{ url: "x" }] },
  { provider: "gemini", ok: true, sources: [{ url: "y" }] },
]);
assert.equal(coverage.successfulProviders, 2);
assert.equal(coverage.successfulAttempts, 2);
assert.equal(coverage.sufficient, false);
// The blog source shares no query terms, so the relevance gate excludes it.
assert.equal(coverage.uniqueCanonicalUrls, 1);
assert.equal(coverage.offTopicSources, 1);

const repeatedCoverage = retrievalCoverage(fused, [
  { provider: "exa", ok: true, sources: [{ url: "x" }] },
  { provider: "exa", ok: true, sources: [{ url: "y" }] },
  { provider: "exa", ok: true, sources: [{ url: "z" }] },
]);
assert.equal(repeatedCoverage.successfulProviders, 1);
assert.equal(repeatedCoverage.successfulAttempts, 3);

const capabilities = normalizeCapabilities({
  harness: "test",
  providerPin: true,
  providers: ["exa", "gemini", "xai", "firecrawl", "tavily"],
  roles: {
    exa: ["semantic", "developer"],
    gemini: ["general", "fresh"],
    xai: ["fresh", "social"],
    firecrawl: ["developer"],
    tavily: ["general", "semantic"],
  },
});
const plan = planFusion("深入调研 React Server Components 最新实现", capabilities, {});
assert.equal(plan.fusionMode, "provider-fusion");
assert.equal(plan.providers.length, 3);
assert.ok(plan.queryVariants.length >= 2);
assert.equal(plan.waves.breadth.length, 3);
assert.ok(plan.waves.breadth.every(item => item.query === plan.waves.breadth[0].query));
assert.ok(plan.waves.breadth.length + plan.waves.facets.length < 9);

const duplicated = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
], "same provider repeat", { freshness: "evergreen" }, capabilities);
const supported = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
  { provider: "gemini", ok: true, sources: [{ url: "https://example.com/a" }] },
], "same provider repeat", { freshness: "evergreen" }, capabilities);
assert.ok(supported[0].rrf > duplicated[0].rrf);
assert.equal(duplicated[0].providerSupport, 1);

const paris = classifyQuery("巴黎天气怎么样");
assert.equal(paris.domain, "general");
assert.equal(paris.language, "mixed-or-zh");

const phones = classifyQuery("iPhone 18 和 Galaxy S26 哪个好");
assert.equal(phones.task, "comparison");
assert.equal(phones.domain, "general");
assert.equal(phones.depth, "verify");
assert.equal(phones.language, "mixed-or-zh");

const chinaTopic = classifyQuery("中国搜索引擎现状");
assert.equal(chinaTopic.domain, "china");

function topRrf(semantics) {
  return fuseProviderResults(
    [{ provider: "p", ok: true, sources: [{ url: "https://example.com/a", title: "A", snippet: "hello world docs" }] }],
    "hello world docs",
    { freshness: "evergreen" },
    { rankSemantics: { p: semantics } },
  )[0].rrf;
}
assert.ok(Math.abs(topRrf("ranked") - topRrf("citation-order")) < 1e-12);
assert.ok(Math.abs(topRrf("ranked") - topRrf("unknown")) < 1e-12);

const ratioFused = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
  { provider: "gemini", ok: true, sources: [{ url: "https://example.com/a" }] },
], "q", { freshness: "evergreen" }, { rankSemantics: { exa: "ranked", gemini: "citation-order" } });
assert.equal(ratioFused[0].providerSupport, 2);
assert.equal(ratioFused[0].providerSupportRatio, 1);

const emptyCaps = normalizeCapabilities({ harness: "omp", level: "L3", providerPin: true, providers: [] });
assert.equal(emptyCaps.level, "L0");
assert.equal(emptyCaps.providers.length, 0);

const seen = [];
await mapSearchCalls(["a", "b"], async item => {
  seen.push(`s${item}`);
  await new Promise(resolve => setTimeout(resolve, 5));
  seen.push(`e${item}`);
  return item;
}, false);
assert.deepEqual(seen, ["sa", "ea", "sb", "eb"]);

const familyCaps = normalizeCapabilities({
  providerPin: true,
  providers: ["gemini", "startpage", "exa"],
  autoOrder: ["gemini", "startpage", "exa"],
});
const familySelected = selectProvidersByRole(
  { task: "factual", domain: "general", freshness: "evergreen" },
  familyCaps,
  { count: 2 },
);
assert.deepEqual(familySelected, ["gemini", "exa"]);

const sameFamily = fuseProviderResults([
  { provider: "gemini", ok: true, sources: [{ url: "https://example.com/a", title: "A" }] },
  { provider: "startpage", ok: true, sources: [{ url: "https://example.com/a", title: "A" }] },
], "q", { freshness: "evergreen" }, {
  rankSemantics: { gemini: "citation-order", startpage: "ranked" },
  retrievalFamilies: { gemini: "google", startpage: "google" },
});
const differentFamily = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a" }] },
  { provider: "gemini", ok: true, sources: [{ url: "https://example.com/a" }] },
], "q", { freshness: "evergreen" }, {
  rankSemantics: { exa: "ranked", gemini: "citation-order" },
  retrievalFamilies: { exa: "exa", gemini: "google" },
});
assert.equal(sameFamily[0].providerSupport, 2);
assert.equal(sameFamily[0].familySupport, 1);
assert.equal(differentFamily[0].familySupport, 2);
assert.ok(differentFamily[0].rrf > sameFamily[0].rrf);

console.log("search-fusion core checks passed");
