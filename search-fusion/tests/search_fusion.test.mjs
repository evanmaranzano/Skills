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

console.log("search-fusion cli checks passed");
