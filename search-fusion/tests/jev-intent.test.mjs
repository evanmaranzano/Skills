import assert from "node:assert/strict";

import { ambiguousAxes, classifyQuery } from "../core/classify.mjs";
import { defaultProviderIds, providerDescriptions } from "../core/capabilities.mjs";
import { AXIS_QUESTIONS, buildProviderCatalog, jevEnabled, PROVIDER_PICK_LIMIT, refineIntentWithJev } from "../core/jev-intent.mjs";
import { mergeJevProviders } from "../core/plan.mjs";
import { parseArgs } from "../scripts/search-fusion.mjs";

// Machine env (e.g. SEARCH_FUSION_JEV=0) must not flip reasons in this file.
delete process.env.SEARCH_FUSION_JEV;

// Freshness guard: the capability catalog routes on these descriptions, so
// every known provider must have one and none may linger for removed ids.
assert.deepEqual(
  Object.keys(providerDescriptions()).sort(),
  [...defaultProviderIds()].sort(),
  "descriptions must exactly cover the provider set (add one when adding a provider)",
);

const comparison = "横评 Exa 和 Tavily 的最新搜索能力";
assert.deepEqual(ambiguousAxes(comparison), []);
assert.equal(classifyQuery(comparison).task, "comparison");

const vague = "帮我看看这个东西";
assert.deepEqual(ambiguousAxes(vague).sort(), ["depth", "domain", "freshness", "task"]);

const phones = ambiguousAxes("iPhone 18 和 Galaxy S26 哪个好");
assert.equal(phones.includes("task"), false);
assert.equal(phones.includes("depth"), false);
assert.ok(phones.includes("freshness"));
assert.ok(phones.includes("domain"));
assert.ok(!ambiguousAxes("中国搜索引擎现状").includes("domain"));
assert.ok(!ambiguousAxes("中国搜索引擎现状").includes("freshness"));
assert.ok(ambiguousAxes("中国搜索引擎现状").includes("task"));

assert.equal(ambiguousAxes(vague, { task: "factual" }).includes("task"), false);
assert.equal(jevEnabled({ noJev: true }), false);
assert.equal(jevEnabled({ benchmarkProfile: "search-api" }), false);

const parsed = parseArgs(["--plan", "--no-jev", "帮我看看这个东西"]);
assert.equal(parsed.options.noJev, true);
assert.equal(parsed.options.plan, true);

let fetchCalls = 0;
const skipped = await refineIntentWithJev(
  comparison,
  classifyQuery(comparison),
  {},
  { fetch: async () => { fetchCalls += 1; throw new Error("should not fetch"); } },
);
assert.equal(skipped.jev.reason, "rules-confident");
assert.equal(fetchCalls, 0);

const disabled = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  { noJev: true },
  { fetch: async () => { fetchCalls += 1; throw new Error("should not fetch"); } },
);
assert.equal(disabled.jev.reason, "disabled");
assert.equal(fetchCalls, 0);

const noKey = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  {},
  {
    credentials: { apiKey: "", baseUrl: "https://example.invalid", model: "jev-latest" },
    fetch: async () => { fetchCalls += 1; throw new Error("should not fetch"); },
  },
);
assert.equal(noKey.jev.reason, "no-credential");
assert.equal(fetchCalls, 0);

// The endpoint is never baked into the public repo: a key without a base URL
// (env-provided) keeps Jev off, fail-open.
const noEndpoint = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  {},
  {
    credentials: { apiKey: "test-key", baseUrl: "", model: "jev-latest" },
    fetch: async () => { fetchCalls += 1; throw new Error("should not fetch"); },
  },
);
assert.equal(noEndpoint.jev.reason, "no-endpoint");
assert.equal(fetchCalls, 0);

const applied = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  {},
  {
    credentials: { apiKey: "test-key", baseUrl: "https://jev.example", model: "jev-latest" },
    fetch: async (url, init) => {
      fetchCalls += 1;
      assert.equal(url, "https://jev.example/v1/systemone");
      assert.match(init.headers.authorization, /^Bearer test-key$/);
      const body = JSON.parse(init.body);
      assert.deepEqual(Object.keys(body.questions).sort(), ["depth", "domain", "freshness", "task"]);
      return {
        ok: true,
        json: async () => ({
          model: "jev-latest",
          answers: {
            task: { type: "choice", choice: "factual" },
            freshness: { type: "choice", choice: "recent" },
            domain: { type: "choice", choice: "coding" },
            depth: { type: "choice", choice: "verify" },
          },
        }),
      };
    },
  },
);
assert.equal(applied.jev.used, true);
assert.equal(applied.intent.task, "factual");
assert.equal(applied.intent.freshness, "recent");
assert.equal(applied.intent.domain, "coding");
assert.equal(applied.intent.depth, "verify");
assert.ok(applied.intent.domainTags.includes("coding"));

const timedOut = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  {},
  {
    credentials: { apiKey: "test-key", baseUrl: "https://jev.example", model: "jev-latest" },
    timeoutMs: 20,
    fetch: async (_url, init) => {
      await new Promise((_, reject) => {
        init.signal.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reject(error);
        });
      });
    },
  },
);
assert.equal(timedOut.jev.used, false);
assert.equal(timedOut.jev.reason, "timeout");
assert.equal(timedOut.intent.task, "exploratory");

const invalid = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  {},
  {
    credentials: { apiKey: "test-key", baseUrl: "https://jev.example", model: "jev-latest" },
    fetch: async () => ({
      ok: true,
      json: async () => ({
        answers: { task: { type: "choice", choice: "not-a-task" } },
      }),
    }),
  },
);
assert.equal(invalid.intent.task, "exploratory");
assert.equal(invalid.jev.reason, "no-valid-answer");

// Catalog round trip: the catalog rides inside a `routing` question (the
// deployed endpoint rejects extra top-level fields, live-verified), and the
// answer's probability distribution becomes ranked, id-validated picks.
const CATALOG = buildProviderCatalog(
  {
    providers: ["exa", "tavily", "reach-bilibili"],
    roles: { exa: ["semantic"], tavily: ["general"], "reach-bilibili": ["platform:bilibili", "china"] },
    autoOrder: ["exa", "tavily", "reach-bilibili"],
  },
  { scores: { exa: 0.9, tavily: 0.7 } },
);
assert.deepEqual(CATALOG.map(entry => entry.id), ["exa", "tavily", "reach-bilibili"]);
assert.equal(CATALOG[2].kind, "platform");
assert.equal(CATALOG[2].reliability, 0.5, "missing score defaults to 0.5");
assert.equal(CATALOG[0].reliability, 0.9);
assert.ok(CATALOG[0].description.length > 10, "descriptions come from provider-defaults");

let routedBody;
const routed = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  {},
  {
    catalog: CATALOG,
    credentials: { apiKey: "test-key", baseUrl: "https://jev.example", model: "jev-latest" },
    fetch: async (url, init) => {
      assert.equal(url, "https://jev.example/v1/systemone");
      routedBody = JSON.parse(init.body);
      return {
        ok: true,
        json: async () => ({
          answers: {
            task: { choice: "exploratory" },
            routing: {
              choice: "reach-bilibili",
              probabilities: { "reach-bilibili": 0.45, tavily: 0.35, exa: 0.15, "not-a-provider": 0.04 },
            },
          },
        }),
      };
    },
  },
);
assert.equal(routedBody.catalog, undefined, "no top-level catalog: the endpoint rejects extra fields");
assert.ok(routedBody.questions.routing, "routing question carries the catalog");
assert.deepEqual(Object.keys(routedBody.questions.routing.criteria), ["exa", "tavily", "reach-bilibili"]);
assert.match(routedBody.questions.routing.criteria["reach-bilibili"], /platform:bilibili/);
assert.deepEqual(
  routed.providers,
  [{ id: "reach-bilibili", weight: 0.45 }, { id: "tavily", weight: 0.35 }, { id: "exa", weight: 0.15 }],
  "unknown ids dropped, sub-5% noise dropped, probability-ranked",
);
assert.equal(routed.jev.used, true);
assert.deepEqual(routed.jev.providers, routed.providers);

// Legacy server (choice only, no probabilities): the argmax becomes the pick.
const legacy = await refineIntentWithJev(
  vague,
  classifyQuery(vague),
  {},
  {
    catalog: CATALOG,
    credentials: { apiKey: "test-key", baseUrl: "https://jev.example", model: "jev-latest" },
    fetch: async () => ({
      ok: true,
      json: async () => ({
        answers: { depth: { choice: "deep" }, routing: { choice: "tavily" } },
      }),
    }),
  },
);
assert.equal(legacy.intent.depth, "deep");
assert.deepEqual(legacy.providers, [{ id: "tavily", weight: 1 }]);

// Provider picks are suggestions: they boost reliability scores for selection
// but cannot inject a provider that is not in the live pool.
const merged = mergeJevProviders({ exa: 0.9, tavily: 0.7 }, [{ id: "reach-bilibili", weight: 0.8 }, { id: "tavily", weight: 0.5 }, "not-in-pool"]);
assert.equal(merged["reach-bilibili"], undefined);
assert.ok(Math.abs(merged.tavily - 0.9) < 1e-9, "0.7 + 0.4*0.5");
assert.equal(merged.exa, 0.9, "unpicked providers untouched");
assert.deepEqual(mergeJevProviders({ exa: 0.9 }, undefined), { exa: 0.9 });

// Axis questions are exported for the agent-fallback decision block.
assert.ok(AXIS_QUESTIONS.task.criteria.comparison.length > 0);

console.log("jev-intent.test.mjs: all assertions passed");
