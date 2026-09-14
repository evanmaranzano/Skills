import assert from "node:assert/strict";
import { createHostAdapter, normalizeHostSearchResult } from "../adapters/host.mjs";

const response = normalizeHostSearchResult("fixture", {
  details: {
    response: {
      answer: "Fixture answer",
      sources: [
        { title: "A", url: "https://example.com/a", snippet: "Alpha" },
        { url: "" },
      ],
      citations: [{ url: "https://example.com/a" }],
    },
  },
});
assert.equal(response.provider, "fixture");
assert.equal(response.sources.length, 1);
assert.deepEqual(response.citations, ["https://example.com/a"]);

const adapter = createHostAdapter({
  harness: "fixture-host",
  providers: ["exa", "gemini"],
  search: async request => ({ response: { sources: [{ title: "R", url: `https://example.com/${request.provider}` }] } }),
});
const capabilities = await adapter.capabilities();
assert.equal(capabilities.level, "L3");
assert.equal(capabilities.providerPin, true);
const searched = await adapter.search({ query: "x", provider: "exa" });
assert.equal(searched.sources[0].url, "https://example.com/exa");

const generic = createHostAdapter({
  harness: "generic",
  providers: [],
  search: async () => ({ sources: [{ url: "https://example.com/x" }] }),
});
const genericCaps = await generic.capabilities();
assert.equal(genericCaps.level, "L1");
assert.equal(genericCaps.providerPin, false);
assert.deepEqual(genericCaps.providers, ["host"]);
assert.ok(genericCaps.retrievalFamilies);

console.log("search-fusion host adapter checks passed");
