import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import { classifyProvenance, provenanceScore } from "../core/provenance.mjs";
import { strictCanonicalUrl, looseCanonicalUrl, normalizeUrl } from "../core/normalize.mjs";
import { defaultProviderRoles, defaultRetrievalFamilies } from "../core/capabilities.mjs";
import { fuseProviderResults } from "../core/fuse.mjs";
import { parseArgs, runSearchFusion } from "../scripts/search-fusion.mjs";

assert.equal(classifyProvenance("https://github.com/openai/openai-python"), "code");
assert.ok(provenanceScore("https://github.com/openai/openai-python") < provenanceScore("https://developers.openai.com/api/docs"));
assert.equal(classifyProvenance("https://docs.evil-example.com/foo"), "unknown");
assert.equal(classifyProvenance("https://developers.openai.com/api/docs"), "primary_official");
assert.equal(classifyProvenance("https://arxiv.org/abs/123"), "primary_paper");

const tracked = "https://www.example.com/a/?utm_source=test&b=2#part";
assert.equal(normalizeUrl(tracked), "https://example.com/a?b=2");
assert.equal(looseCanonicalUrl(tracked), "https://example.com/a?b=2");
assert.equal(strictCanonicalUrl(tracked), "https://www.example.com/a/?b=2#part");
assert.notEqual(strictCanonicalUrl("https://www.example.com/a"), looseCanonicalUrl("https://www.example.com/a"));
assert.equal(looseCanonicalUrl("https://www.example.com/a/"), looseCanonicalUrl("https://example.com/a"));

const roles = defaultProviderRoles(["exa", "gemini", "startpage"]);
assert.deepEqual(roles.exa, ["semantic", "developer", "academic"]);
assert.equal(defaultRetrievalFamilies(["gemini", "startpage"]).gemini, "google");
assert.equal(defaultRetrievalFamilies(["gemini", "startpage"]).startpage, "google");

const first = fuseProviderResults([
  { provider: "exa", ok: true, sources: [{ url: "https://example.com/a?utm_source=1" }] },
  { provider: "gemini", ok: true, sources: [{ url: "https://www.example.com/a/" }] },
], "q", { freshness: "evergreen" }, { rankSemantics: { exa: "ranked", gemini: "citation-order" }, retrievalFamilies: { exa: "exa", gemini: "google" } });
assert.equal(first.length, 1);

const replay = parseArgs(["--replay", "results.json", "current docs"]);
assert.equal(replay.options.input, "results.json");

const fixture = fileURLToPath(new URL("./fixtures/host-results.json", import.meta.url));
const once = await runSearchFusion("current OpenAI API documentation", { input: fixture, top: 8 });
const twice = await runSearchFusion("current OpenAI API documentation", { input: fixture, top: 8 });
assert.equal(once.schemaVersion, 1);
assert.ok(once.capabilities);
assert.ok(Array.isArray(once.attempts));
assert.deepEqual(once.results.map(source => source.url), twice.results.map(source => source.url));
assert.deepEqual(once.results.map(source => source.score), twice.results.map(source => source.score));

console.log("search-fusion property checks passed");
