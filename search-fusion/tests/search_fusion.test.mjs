import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { parseArgs, runSearchFusion } from "../scripts/search-fusion.mjs";

const shim = readFileSync(fileURLToPath(new URL("../scripts/search_fusion.mjs", import.meta.url)), "utf8");
assert.ok(shim.length < 1500);
assert.match(shim, /search-fusion\.mjs/);
assert.doesNotMatch(shim, /PROVIDER_WEIGHTS|agreementScore|AUTHORITY_FALLBACK/);

assert.throws(() => parseArgs(["just a query"]), /No execution mode selected/);
const parsed = parseArgs(["--adapter", "omp", "--pretty", "foo bar"]);
assert.equal(parsed.query, "foo bar");
assert.equal(parsed.options.adapter, "omp");
assert.equal(parsed.options.pretty, true);
const replay = parseArgs(["--replay", "fixture.json", "q"]);
assert.equal(replay.options.input, "fixture.json");

await assert.rejects(() => runSearchFusion("x", {}), /No execution mode selected/);

// Hermetic replay: --input and provider-less --plan never consult Jev, even
// with credentials present and an endpoint that would fail loudly if called.
const fixture = fileURLToPath(new URL("./fixtures/host-results.json", import.meta.url));
const envBackup = { ...process.env };
process.env.SEARCH_FUSION_JEV_API_KEY = "hermetic-test";
process.env.SEARCH_FUSION_JEV_BASE_URL = "http://127.0.0.1:9";
try {
  const replayed = await runSearchFusion("current OpenAI API documentation", { input: fixture });
  assert.equal(replayed.runManifest.intentJev.reason, "no-routing-path");
  const planned = await runSearchFusion("帮我看看这个东西", { plan: true, noCache: true });
  assert.equal(planned.decision.jev.reason, "no-routing-path");
} finally {
  process.env.SEARCH_FUSION_JEV_API_KEY = envBackup.SEARCH_FUSION_JEV_API_KEY;
  process.env.SEARCH_FUSION_JEV_BASE_URL = envBackup.SEARCH_FUSION_JEV_BASE_URL;
  if (envBackup.SEARCH_FUSION_JEV_API_KEY === undefined) delete process.env.SEARCH_FUSION_JEV_API_KEY;
  if (envBackup.SEARCH_FUSION_JEV_BASE_URL === undefined) delete process.env.SEARCH_FUSION_JEV_BASE_URL;
}

console.log("search-fusion cli checks passed");
