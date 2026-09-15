import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createDirectAdapter } from "../adapters/direct.mjs";
import { detectProviderAuth, renderDoctorReport, readyDirectProviders, resolveCredential } from "../core/provider-auth.mjs";
import { loadStoredToken, clearStoredToken, tokenIsFresh, OAUTH_CLIENTS } from "../core/oauth.mjs";

// --- auth detection (injected env, never touches real credentials) ---

const env = { EXA_API_KEY: "test-exa-key", TAVILY_API_KEY: "test-tavily-key" };
assert.equal(detectProviderAuth("exa", env).status, "ready");
assert.equal(detectProviderAuth("exa", env).mode.var, "EXA_API_KEY");
assert.equal(detectProviderAuth("tavily", env).status, "ready");
assert.equal(detectProviderAuth("duckduckgo", env).status, "keyless");
assert.equal(detectProviderAuth("brave", env).status, "missing");
assert.equal(detectProviderAuth("openai", env).status, "missing"); // oauth-only, no keyless
assert.deepEqual(readyDirectProviders(env).sort(), ["duckduckgo", "exa", "tavily"].sort());

const report = renderDoctorReport(env);
assert.match(report, /✅ Exa \(exa\): ready via EXA_API_KEY/);
assert.match(report, /❌ Brave Search \(brave\): not configured/);
assert.match(report, /set BRAVE_API_KEY/);
assert.match(report, /🌐 DuckDuckGo \(duckduckgo\): keyless/);
assert.ok(!report.includes("test-exa-key"), "doctor output must not leak key values");

// --- direct adapter capabilities ---

const adapter = createDirectAdapter({ env });
const capabilities = await adapter.capabilities();
assert.equal(capabilities.harness, "direct");
assert.equal(capabilities.providerPin, true);
assert.ok(capabilities.providers.includes("exa"));
assert.ok(capabilities.providers.includes("tavily"));
assert.ok(capabilities.providers.includes("duckduckgo"));
assert.ok(!capabilities.providers.includes("brave"), "missing-key provider must not be in the pool");
assert.ok(capabilities.roles.exa.length > 0);

// restricted provider subset
const restricted = createDirectAdapter({ env, providers: ["exa"] });
assert.deepEqual((await restricted.capabilities()).providers, ["exa"]);

// unknown provider id is dropped silently (fail-open discovery never lies)
const unknown = createDirectAdapter({ env, providers: ["exa", "nonexistent"] });
assert.deepEqual((await unknown.capabilities()).providers, ["exa"]);

// --- request/response mapping via mocked transport ---

function mockFetchCapture(capture) {
  return async (url, init) => {
    capture.url = String(url);
    capture.init = init;
    return {
      ok: true,
      status: 200,
      text: async () => capture.raw ?? JSON.stringify(capture.payload ?? {}),
      headers: new Map(),
    };
  };
}

// exa: x-api-key header + POST body
{
  const capture = { payload: { results: [{ url: "https://a.example", title: "A", text: "snippet", publishedDate: "2026-09-01" }] } };
  const testAdapter = createDirectAdapter({ env, providers: ["exa"] });
  testAdapter.__setFetchForTests(mockFetchCapture(capture));
  const out = await testAdapter.search({ provider: "exa", query: "q", limit: 5, recency: "week" });
  assert.equal(capture.init.headers["x-api-key"], "test-exa-key");
  const body = JSON.parse(capture.init.body);
  assert.equal(body.query, "q");
  assert.ok(body.startPublishedDate, "recency maps to startPublishedDate");
  assert.equal(out.sources[0].url, "https://a.example");
  assert.equal(out.metadata.authMode, "env-key");
}

// tavily: Bearer header + answer passthrough
{
  const capture = { payload: { results: [{ url: "https://b.example", title: "B", content: "c" }], answer: "synthesized" } };
  const testAdapter = createDirectAdapter({ env, providers: ["tavily"] });
  testAdapter.__setFetchForTests(mockFetchCapture(capture));
  const out = await testAdapter.search({ provider: "tavily", query: "q" });
  assert.equal(capture.init.headers.Authorization, "Bearer test-tavily-key");
  assert.equal(out.answer, "synthesized");
  assert.equal(out.sources[0].snippet, "c");
}

// brave: X-Subscription-Token + freshness param
{
  const capture = { payload: { web: { results: [{ url: "https://c.example", title: "C", description: "d" }] } } };
  const testAdapter = createDirectAdapter({ env: { BRAVE_API_KEY: "k" }, providers: ["brave"] });
  testAdapter.__setFetchForTests(mockFetchCapture(capture));
  const out = await testAdapter.search({ provider: "brave", query: "q", recency: "week" });
  assert.equal(capture.init.headers["X-Subscription-Token"], "k");
  assert.match(capture.url, /freshness=pw/);
  assert.equal(out.sources[0].url, "https://c.example");
}

// auth error classification: 401 → auth failure
{
  const testAdapter = createDirectAdapter({ env: { EXA_API_KEY: "bad" }, providers: ["exa"] });
  testAdapter.__setFetchForTests(async () => ({ ok: false, status: 401, text: async () => "unauthorized", headers: new Map() }));
  await assert.rejects(
    () => testAdapter.search({ provider: "exa", query: "q" }),
    error => error.searchFusionType === "auth",
  );
}

// missing credential refuses before any network call
{
  const testAdapter = createDirectAdapter({ env: {}, providers: ["exa"] });
  assert.deepEqual((await testAdapter.capabilities()).providers, []);
  await assert.rejects(
    () => testAdapter.search({ provider: "exa", query: "q" }),
    error => error.searchFusionType === "auth",
  );
}


// --- OAuth: token store, detection, mode selection, gemini dual-mode ---

const fakeHome = mkdtempSync(join(tmpdir(), "sf-oauth-test-"));
const futureExpiry = Date.now() + 3600000;

// store + detect (gemini supports OAuth; no env key in this env object)
{
  const oauthEnv = {}; // deliberately no GEMINI_API_KEY
  assert.equal(detectProviderAuth("gemini", oauthEnv, fakeHome).status, "missing");
  const store = JSON.parse("null") ?? {};
  // simulate what --login gemini persists (no network involved)
  const authFile = join(fakeHome, ".search-fusion", "auth.json");
  const { mkdirSync, writeFileSync } = await import("node:fs");
  mkdirSync(join(fakeHome, ".search-fusion"), { recursive: true });
  writeFileSync(authFile, JSON.stringify({ "gemini-cli": { access_token: "at", refresh_token: "rt", expiresAt: futureExpiry, email: "t@example.com", projectId: "proj-test" } }));
  const detection = detectProviderAuth("gemini", oauthEnv, fakeHome);
  assert.equal(detection.status, "ready");
  assert.equal(detection.via, "oauth");
  assert.equal(detection.mode.email, "t@example.com");
  assert.equal(tokenIsFresh(loadStoredToken("gemini-cli", fakeHome)), true);
  assert.deepEqual(resolveCredential("gemini", "auto", oauthEnv, fakeHome).kind, "oauth");
  assert.deepEqual(resolveCredential("gemini", "oauth", oauthEnv, fakeHome).kind, "oauth");
  assert.deepEqual(resolveCredential("gemini", "key", oauthEnv, fakeHome).kind, null, "key mode must not fall back to oauth");
  const report = renderDoctorReport(oauthEnv, null, fakeHome);
  assert.match(report, /ready via oauth token \(t@example\.com\)/);
}

// key mode prefers env even when oauth token exists
{
  const envBoth = { GEMINI_API_KEY: "test-gemini-key" };
  assert.deepEqual(resolveCredential("gemini", "auto", envBoth, fakeHome).kind, "env-key");
  assert.deepEqual(resolveCredential("gemini", "key", envBoth, fakeHome).kind, "env-key");
  assert.deepEqual(resolveCredential("gemini", "oauth", envBoth, fakeHome).kind, "oauth", "explicit oauth must win over env key");
}

// gemini builder: oauth -> Authorization bearer; key -> x-goog-api-key
async function captureGemini(envObject, authMode, home) {
  const inner = { candidates: [{ content: { parts: [{ text: "answer" }] }, groundingMetadata: { groundingChunks: [{ web: { uri: "https://g.example", title: "G" } }] }, webSearchQueries: ["q"] }] };
  const capture = authMode === "oauth"
    ? { raw: `data: ${JSON.stringify(inner)}

` }
    : { payload: inner };
  const testAdapter = createDirectAdapter({ env: envObject, providers: ["gemini"], authMode, home });
  testAdapter.__setFetchForTests(mockFetchCapture(capture));
  const out = await testAdapter.search({ provider: "gemini", query: "q" });
  return { capture, out };
}
{
  const envNoKey = {};
  const { capture, out } = await captureGemini(envNoKey, "oauth", fakeHome);
  assert.match(String(capture.init.headers.Authorization), /^Bearer /);
  assert.equal(out.sources[0].url, "https://g.example");
  assert.equal(out.answer, "answer");
  assert.equal(out.metadata.authMode, "oauth");
}
{
  const { capture, out } = await captureGemini({ GEMINI_API_KEY: "test-gemini-key" }, "key", fakeHome);
  assert.equal(capture.init.headers["x-goog-api-key"], "test-gemini-key");
  assert.equal(capture.init.headers.Authorization, undefined);
  assert.equal(out.metadata.authMode, "env-key");
}

// logout removes the token
assert.equal(clearStoredToken("gemini-cli", fakeHome), true);
assert.equal(loadStoredToken("gemini-cli", fakeHome), null);
assert.equal(detectProviderAuth("gemini", {}, fakeHome).status, "missing");
rmSync(fakeHome, { recursive: true, force: true });

// oauth client registry sanity: public installed-app clients per gemini-cli / OMP
assert.ok(OAUTH_CLIENTS["gemini-cli"].clientId.endsWith(".apps.googleusercontent.com"));
assert.ok(OAUTH_CLIENTS["gemini-cli"].scopes.some(scope => scope.endsWith("cloud-platform")));
assert.ok(OAUTH_CLIENTS.antigravity.clientId.endsWith(".apps.googleusercontent.com"));
assert.equal(OAUTH_CLIENTS.antigravity.callback.port, 51121);

console.log("search-fusion direct adapter checks passed");
