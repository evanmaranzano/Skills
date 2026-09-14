import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import { runSearchFusion } from "../scripts/search-fusion.mjs";

const fixture = fileURLToPath(new URL("./fixtures/host-results.json", import.meta.url));
const output = await runSearchFusion("current OpenAI API documentation", {
  input: fixture,
  top: 8,
});

assert.equal(output.mode, "host-orchestrated");
assert.equal(output.schemaVersion, 1);
assert.equal(output.results[0].url, "https://developers.openai.com/api/docs");
assert.equal(output.results[0].providerSupport, 2);
assert.equal(output.results[0].familySupport, 2);
assert.ok(Array.isArray(output.facets));
assert.equal(output.facets[0].id, "base");
assert.equal(output.queryVariants[0], "current OpenAI API documentation");
assert.equal(output.coverage.retrieval.successfulProviders, 2);
assert.ok(output.capabilities);
assert.ok(Array.isArray(output.attempts));

console.log("search-fusion replay checks passed");
