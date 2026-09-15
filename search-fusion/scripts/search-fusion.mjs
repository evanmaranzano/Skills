#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

import { classifyQuery } from "../core/classify.mjs";
import { mapSearchCalls, normalizeCapabilities, planFusion, planSearchWaves, selectProvidersByRole } from "../core/plan.mjs";
import { decomposeQuery, facetQueries } from "../core/decompose.mjs";
import { fuseProviderResults } from "../core/fuse.mjs";
import { diversifySources } from "../core/rerank.mjs";
import { combinedCoverage, evidenceCoverage } from "../core/coverage.mjs";
import { normalizeSearchBudget } from "../core/budget.mjs";
import { configDigest } from "../core/load-config.mjs";
import { SEARCH_FUSION_VERSION } from "../core/version.mjs";

const NO_MODE_ERROR = [
  "No execution mode selected.",
  "",
  "Use:",
  "  --input results.json",
  "or:",
  "  --adapter <name>",
].join("\n");

const ENUM_OPTIONS = {
  authMode: ["auto", "key", "oauth"],
  benchmarkProfile: ["search-api", "research-system"],
  task: ["lookup", "comparison", "tutorial", "exploratory", "factual"],
  freshness: ["evergreen", "recent", "live"],
  domain: ["general", "coding", "academic", "news", "china"],
  depth: ["quick", "verify", "deep"],
};
const NUMERIC_OPTIONS = new Set(["limit", "top", "providerCount", "maxSubqueries", "maxSearchCalls", "maxFallbackCalls", "perCallTimeoutMs", "timeoutMs", "maxFetches"]);

function sanitizeError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message
    .replace(/(api[-_ ]?key|authorization|bearer|token|secret)([\s=:]+)[^\s,;]+/gi, "$1$2[redacted]")
    .replace(/\b(?:sk|tvly|fc|fcs|exa)[-_][A-Za-z0-9._-]{8,}\b/gi, "[redacted]");
}

function errorType(error) {
  if (!error) return "unknown";
  if (error.searchFusionType) return error.searchFusionType;
  const message = error instanceof Error ? error.message : String(error);
  if (/timeout|abort|deadline/i.test(error.name ?? "") || /timeout|abort|deadline/i.test(message)) return "timeout";
  if (/auth|permission|unauthorized|forbidden|\b401\b|\b403\b/i.test(message)) return "auth";
  if (/rate.?limit|\b429\b/i.test(message)) return "rate_limit";
  if (/network|econn|enotfound|fetch failed|socket|dns/i.test(message)) return "network";
  if (error instanceof TypeError) return "type";
  return "provider";
}

export function parseArgs(argv) {
  const options = {
    adapter: undefined,
    asOf: undefined,
    benchmarkProfile: undefined,
    capabilities: undefined,
    depth: undefined,
    doctor: false,
    live: false,
    domain: undefined,
    freshness: undefined,
    input: undefined,
    limit: 6,
    maxFallbackCalls: undefined,
    maxFetches: undefined,
    maxSearchCalls: undefined,
    maxSubqueries: 3,
    next: false,
    output: undefined,
    perCallTimeoutMs: undefined,
    plan: false,
    pretty: false,
    providerCount: 3,
    providers: undefined,
    recency: undefined,
    strictProviderPin: false,
    task: undefined,
    timeoutMs: undefined,
    top: 8,
  };
  const queryParts = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") return { help: true };
    if (arg === "--doctor") { options.doctor = true; continue; }
    if (arg === "--login") { options.login = argv[++index]; continue; }
    if (arg === "--logout") { options.logout = argv[++index]; continue; }
    if (arg === "--auth-mode") { options.authMode = argv[++index]; continue; }
    if (arg === "--live") { options.live = true; continue; }
    if (arg === "--pretty") { options.pretty = true; continue; }
    if (arg === "--plan") { options.plan = true; continue; }
    if (arg === "--next") { options.next = true; continue; }
    if (arg === "--strict-provider-pin") { options.strictProviderPin = true; continue; }
    if (arg === "--adapter") { options.adapter = argv[++index]; continue; }
    if (arg === "--capabilities") { options.capabilities = argv[++index]; continue; }
    if (arg === "--providers") { options.providers = String(argv[++index]).split(",").map(item => item.trim()).filter(Boolean); continue; }
    if (arg === "--benchmark-profile") { options.benchmarkProfile = argv[++index]; continue; }
    if (arg === "--input" || arg === "--replay") { options.input = argv[++index]; continue; }
    if (arg === "--output") { options.output = argv[++index]; continue; }
    if (arg === "--task") { options.task = argv[++index]; continue; }
    if (arg === "--freshness") { options.freshness = argv[++index]; continue; }
    if (arg === "--domain") { options.domain = argv[++index]; continue; }
    if (arg === "--depth") { options.depth = argv[++index]; continue; }
    if (arg === "--recency") { options.recency = argv[++index]; continue; }
    if (arg === "--as-of") { options.asOf = argv[++index]; continue; }
    if (arg === "--limit") { options.limit = Number(argv[++index]); continue; }
    if (arg === "--top") { options.top = Number(argv[++index]); continue; }
    if (arg === "--provider-count") { options.providerCount = Number(argv[++index]); continue; }
    if (arg === "--max-subqueries") { options.maxSubqueries = Number(argv[++index]); continue; }
    if (arg === "--max-search-calls") { options.maxSearchCalls = Number(argv[++index]); continue; }
    if (arg === "--max-fallback-calls") { options.maxFallbackCalls = Number(argv[++index]); continue; }
    if (arg === "--max-fetches") { options.maxFetches = Number(argv[++index]); continue; }
    if (arg === "--per-call-timeout-ms") { options.perCallTimeoutMs = Number(argv[++index]); continue; }
    if (arg === "--timeout-ms") { options.timeoutMs = Number(argv[++index]); continue; }
    if (arg.startsWith("--")) {
      const [key, value] = arg.slice(2).split("=", 2);
      const normalizedKey = key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      if (!Object.hasOwn(options, normalizedKey)) throw new Error(`Unknown option: ${arg}`);
      if (["pretty", "plan", "next", "strictProviderPin"].includes(normalizedKey)) { options[normalizedKey] = true; continue; }
      options[normalizedKey] = NUMERIC_OPTIONS.has(normalizedKey) ? Number(value) : value;
      continue;
    }
    queryParts.push(arg);
  }
  const query = queryParts.join(" ").trim();
  if (!query && !options.doctor) throw new Error("A search query is required");
  if (!options.doctor && !options.plan && !options.input && !options.adapter && !options.capabilities) throw new Error(NO_MODE_ERROR);
  if (options.next && !options.input) throw new Error("--next requires --input <file>");
  if (options.recency && !["day", "week", "month", "year"].includes(options.recency)) throw new Error("--recency must be day, week, month, or year");
  for (const [name, allowed] of Object.entries(ENUM_OPTIONS)) {
    if (options[name] && !allowed.includes(options[name])) {
      throw new Error(`--${name.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)} must be one of ${allowed.join(", ")}`);
    }
  }
  for (const name of NUMERIC_OPTIONS) {
    const value = options[name];
    if (value === undefined) continue;
    if (!Number.isInteger(value) || value < 1) throw new Error(`--${name.replace(/[A-Z]/g, c => `-${c.toLowerCase()}`)} must be a positive integer`);
  }
  if (options.timeoutMs !== undefined && options.timeoutMs < 1000) throw new Error("--timeout-ms must be at least 1000");
  if (options.asOf !== undefined && Number.isNaN(Date.parse(options.asOf))) throw new Error("--as-of must be a parseable date");
  return { query, options };
}

function applyBenchmarkProfile(options) {
  if (options.benchmarkProfile === "search-api") {
    return {
      maxFallbackCalls: 0,
      maxSearchCalls: 5,
      ...options,
      strictProviderPin: true,
    };
  }
  return options;
}

function runManifest({ startedAt, asOf, options, attempts }) {
  const manifest = {
    searchFusionVersion: SEARCH_FUSION_VERSION,
    schemaVersion: 1,
    benchmarkProfile: options.benchmarkProfile ?? null,
    configDigests: {
      providerDefaults: configDigest("../config/provider-defaults.json", import.meta.url),
      sourceProvenance: configDigest("../config/source-provenance.json", import.meta.url),
    },
    retrievedAt: new Date(startedAt).toISOString(),
    asOf: new Date(asOf).toISOString(),
  };
  if (attempts) {
    const providerCalls = {};
    for (const attempt of attempts) {
      providerCalls[attempt.provider] = (providerCalls[attempt.provider] ?? 0) + 1;
    }
    manifest.cost = {
      budgetUnit: "underlying-search-call",
      underlyingSearchCalls: attempts.length,
      providerCalls,
    };
  }
  return manifest;
}

async function loadAdapter(adapterName, capabilitiesPath, options) {
  if (capabilitiesPath) {
    const capabilities = JSON.parse(await readFile(capabilitiesPath, "utf8"));
    const normalized = normalizeCapabilities(capabilities);
    if (!capabilities.adapter) throw new Error("A capability file must specify an adapter module");
    const module = await import(pathToFileURL(path.resolve(capabilities.adapter)).href);
    if (typeof module.createAdapter !== "function") throw new Error("Adapter module must export createAdapter()");
    return { adapter: module.createAdapter(), capabilities: normalized };
  }

  if (!adapterName) throw new Error(NO_MODE_ERROR);
  if (adapterName === "omp" || adapterName === "omp-internal") {
    const module = await import("../adapters/omp-internal.mjs");
    return { adapter: module.createOmpInternalAdapter() };
  }
  if (adapterName === "direct") {
    const module = await import("../adapters/direct.mjs");
    return { adapter: module.createDirectAdapter({ providers: options?.providers, authMode: options?.authMode ?? "auto" }) };
  }
  if (adapterName === "host") {
    throw new Error("The host adapter requires an embedding harness; use --input or --capabilities");
  }
  throw new Error(`Unknown adapter: ${adapterName}`);
}

export async function withTimeout(promise, timeoutMs, abortSignal) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          abortSignal?.abort?.();
          reject(new Error(`Search Fusion deadline exceeded after ${timeoutMs}ms`));
        }, timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function callProvider(adapter, provider, query, options) {
  const startedAt = Date.now();
  const controller = new AbortController();
  const outerSignal = options.signal;
  const onOuterAbort = () => controller.abort();
  outerSignal?.addEventListener?.("abort", onOuterAbort, { once: true });
  const callTimeoutMs = Number.isFinite(options.callTimeoutMs) ? options.callTimeoutMs : undefined;
  let timer;
  try {
    const searchPromise = adapter.search({
      query,
      provider,
      recency: options.recency,
      limit: options.limit,
      signal: controller.signal,
    });
    const response = callTimeoutMs
      ? await Promise.race([
        searchPromise,
        new Promise((_, reject) => {
          timer = setTimeout(() => {
            controller.abort();
            reject(new Error(`call timeout after ${callTimeoutMs}ms`));
          }, callTimeoutMs);
        }),
      ])
      : await searchPromise;
    const actualProvider = response.provider ?? provider;
    if (options.strictProviderPin && actualProvider !== provider) {
      return {
        provider: actualProvider,
        requestedProvider: provider,
        ok: false,
        sources: [],
        error: `strict provider pin: requested ${provider}, got ${actualProvider}`,
        errorType: "provider_mismatch",
        latencyMs: Date.now() - startedAt,
      };
    }
    return {
      provider: actualProvider,
      requestedProvider: provider,
      ok: true,
      sources: response.sources ?? [],
      answer: response.answer,
      citations: response.citations ?? [],
      searchQueries: response.searchQueries ?? [],
      metadata: response.metadata ?? {},
      latencyMs: Date.now() - startedAt,
    };
  } catch (error) {
    return {
      provider,
      requestedProvider: provider,
      ok: false,
      sources: [],
      error: sanitizeError(error),
      errorType: errorType(error),
      latencyMs: Date.now() - startedAt,
    };
  } finally {
    clearTimeout(timer);
    outerSignal?.removeEventListener?.("abort", onOuterAbort);
  }
}

function providerAttemptKey(attempt) {
  return `${attempt.provider}::${attempt.query ?? ""}`;
}

function requireRetrievalPath(capabilities) {
  if (capabilities.level === "L0" || capabilities.providers.length === 0) {
    throw new Error("No searchable retrieval path available");
  }
}

function statusFromCoverage(coverage, partial) {
  if (partial) return { status: "partial", stopReason: "deadline" };
  if (coverage.sufficient) return { status: "complete", stopReason: "coverage-satisfied" };
  return { status: "complete", stopReason: "budget-exhausted" };
}

async function executeFusion(adapter, capabilities, task, query, options, budget, deadlineAt, asOf) {
  const facets = decomposeQuery(query, task, budget.maxSubqueries);
  const queryVariants = facetQueries(facets);
  const pool = capabilities.autoOrder?.length ? capabilities.autoOrder : capabilities.providers;
  const selectedProviders = selectProvidersByRole(task, capabilities, { count: budget.maxInitialProviders });
  const remainingProviders = pool.filter(provider => !selectedProviders.includes(provider));
  const waves = planSearchWaves({
    query,
    facets,
    selectedProviders,
    remainingProviders,
    capabilities,
    budget,
  });
  const attempts = [];
  let partial = false;

  const remainingMs = () => deadlineAt - Date.now();

  async function runAttempts(items, callCeiling = budget.maxSearchCalls) {
    if (remainingMs() < 500) { partial = true; return []; }
    const remainingCalls = Math.max(0, callCeiling - attempts.length);
    const scheduled = items.slice(0, remainingCalls);
    if (scheduled.length === 0) return [];
    const callTimeoutMs = Math.max(1_000, Math.min(budget.perCallTimeoutMs, remainingMs() - 200));
    const results = await mapSearchCalls(
      scheduled,
      item => callProvider(adapter, item.provider, item.query, { ...options, callTimeoutMs }),
      capabilities.parallelSearch,
    );
    results.forEach((result, index) => {
      const item = scheduled[index];
      attempts.push({ ...result, query: item.query, facetId: item.facetId, wave: item.wave });
    });
    return results;
  }

  const score = () => {
    const fused = fuseProviderResults(attempts, query, { ...task, asOf }, capabilities);
    const coverage = combinedCoverage(fused, attempts, query, task, { asOf });
    return { fused, coverage };
  };

  await runAttempts(waves.breadth);
  let { fused, coverage } = score();

  if (!coverage.sufficient && !partial) {
    await runAttempts(waves.facets, budget.maxSearchCalls - waves.fallbackReserve);
    ({ fused, coverage } = score());
  }

  if (!coverage.sufficient && !partial && remainingMs() >= 12_000) {
    for (const item of waves.fallback) {
      if (coverage.sufficient || partial) break;
      await runAttempts([item]);
      ({ fused, coverage } = score());
    }
  }

  if (Date.now() >= deadlineAt) partial = true;
  if (!partial && attempts.some(attempt => !attempt.ok && attempt.errorType === "timeout")) partial = true;
  const diverse = diversifySources(fused, { top: options.top });
  const delivery = evidenceCoverage(diverse, query, task, { asOf });
  return {
    attempts,
    facets,
    queryVariants,
    fused,
    results: diverse,
    coverage: { ...coverage, delivery: { sufficient: delivery.sufficient, gaps: delivery.gaps } },
    budget,
    ...statusFromCoverage(coverage, partial),
    providers: {
      selected: selectedProviders,
      used: [...new Set(attempts.filter(attempt => attempt.ok && attempt.sources.length > 0).map(attempt => attempt.provider))],
      failures: attempts.filter(attempt => !attempt.ok).map(attempt => ({ provider: attempt.provider, requestedProvider: attempt.requestedProvider, error: attempt.error, errorType: attempt.errorType })),
      empty: [...new Set(attempts.filter(attempt => attempt.ok && attempt.sources.length === 0).map(attempt => attempt.provider))],
      autoOrder: capabilities.autoOrder,
    },
  };
}

async function readInput(pathname) {
  const raw = await readFile(pathname, "utf8");
  return JSON.parse(raw);
}

function normalizeInputEnvelope(input, query) {
  const warnings = [];
  if (input === null || typeof input !== "object" || Array.isArray(input)) {
    throw new Error("Fusion input must be a JSON object envelope");
  }
  const rawAttempts = input.attempts ?? input.results;
  if (!Array.isArray(rawAttempts)) {
    throw new Error("Fusion input must contain an attempts or results array");
  }
  if (typeof input.query === "string" && input.query.trim() && input.query.trim() !== query) {
    warnings.push(`input.query "${input.query}" differs from CLI query "${query}"`);
  }
  const attempts = rawAttempts.map((result, index) => {
    if (result === null || typeof result !== "object") {
      warnings.push(`attempt[${index}] is not an object; dropped`);
      return null;
    }
    const sources = Array.isArray(result.sources) ? result.sources.filter(source => {
      const keep = source && typeof source === "object" && typeof source.url === "string";
      if (!keep) warnings.push(`attempt[${index}] has a source without url; dropped`);
      return keep;
    }) : [];
    return { ...result, provider: typeof result.provider === "string" ? result.provider : "unknown", sources, ok: result.ok !== false };
  }).filter(Boolean);
  const asOf = Number.isFinite(Date.parse(input.retrievedAt)) ? Date.parse(input.retrievedAt) : undefined;
  return { attempts, asOf, warnings };
}

function hostResult(query, task, capabilities, attempts, diverse, coverage, startedAt, extras = {}) {
  return {
    schemaVersion: 1,
    mode: "host-orchestrated",
    query,
    task,
    fusionMode: capabilities.providerPin ? "provider-fusion" : capabilities.providers.length > 1 ? "multi-tool-fusion" : "query-diversification",
    capabilities,
    ...extras,
    attempts,
    providers: {
      selected: capabilities.providers,
      used: [...new Set(attempts.filter(result => result.ok && (result.sources ?? []).length > 0).map(result => result.provider))],
      failures: attempts.filter(result => result.ok === false).map(result => ({ provider: result.provider, error: result.error, errorType: result.errorType ?? "provider" })),
      empty: [...new Set(attempts.filter(result => result.ok !== false && (result.sources ?? []).length === 0).map(result => result.provider))],
      autoOrder: capabilities.autoOrder,
    },
    coverage,
    resultCount: diverse.length,
    results: diverse,
    citations: diverse.map((source, index) => `[${index + 1}] ${source.title ?? source.url} — ${source.citationUrl ?? source.url}`),
    providerAnswers: attempts.filter(result => result.answer).map(result => ({ provider: result.provider, answer: result.answer })),
    observability: {
      elapsedMs: Date.now() - startedAt,
      providerLatencyMs: Object.fromEntries(attempts.map(result => [providerAttemptKey(result), result.latencyMs ?? null])),
    },
  };
}

export async function runSearchFusion(rawQuery, rawOptions = {}) {
  const options = applyBenchmarkProfile(rawOptions);
  const query = rawQuery;
  if (!options.plan && !options.input && !options.adapter && !options.capabilities) throw new Error(NO_MODE_ERROR);
  const task = classifyQuery(query, options);
  const budget = normalizeSearchBudget(task, options);
  const startedAt = Date.now();
  const deadlineAt = startedAt + budget.wallClockMs;
  const asOf = Number.isFinite(Date.parse(options.asOf)) ? Date.parse(options.asOf) : startedAt;
  const manifest = attempts => runManifest({ startedAt, asOf, options, attempts });

  if (options.plan) {
    let capabilities = normalizeCapabilities({});
    if (options.adapter || options.capabilities) {
      const { adapter, capabilities: explicit } = await loadAdapter(options.adapter, options.capabilities, options);
      capabilities = explicit ?? normalizeCapabilities(
        await withTimeout(Promise.resolve(adapter.capabilities()), Math.max(1_000, deadlineAt - Date.now())),
      );
    }
    const plan = planFusion(query, capabilities, { ...options, maxSearchCalls: budget.maxSearchCalls });
    const requests = capabilities.providers.length === 0
      ? plan.facets.map(facet => ({
        id: facet.id,
        query: facet.query,
        purpose: facet.purpose,
        requiredRoles: facet.requiredRoles,
        entities: facet.entities,
        provider: null,
        wave: facet.id === "base" ? "breadth" : "facet",
      }))
      : [...plan.waves.breadth, ...plan.waves.facets, ...plan.waves.fallback];
    return {
      schemaVersion: 1,
      action: "plan",
      query,
      task: plan.task,
      capabilities,
      facets: plan.facets,
      queryVariants: plan.queryVariants,
      providerAgnostic: capabilities.providers.length === 0,
      requests,
      budget,
      runManifest: manifest(undefined),
    };
  }

  if (options.input) {
    const input = await readInput(options.input);
    const capabilities = normalizeCapabilities(input.capabilities ?? {});
    const { attempts, asOf: inputAsOf, warnings } = normalizeInputEnvelope(input, query);
    const effectiveAsOf = options.asOf ? asOf : inputAsOf ?? asOf;
    const fused = fuseProviderResults(attempts, query, { ...task, asOf: effectiveAsOf }, capabilities);
    const diverse = diversifySources(fused, { top: options.top ?? 8 });
    const coverage = combinedCoverage(fused, attempts, query, task, { asOf: effectiveAsOf });

    if (options.next) {
      const plan = planFusion(query, capabilities, { ...options, maxSearchCalls: budget.maxSearchCalls });
      const executed = new Set(attempts.map(attempt => `${attempt.provider}::${attempt.query ?? query}`));
      const pending = [...plan.waves.breadth, ...plan.waves.facets, ...plan.waves.fallback]
        .filter(request => !executed.has(`${request.provider}::${request.query}`));
      const remainingCalls = Math.max(0, budget.maxSearchCalls - attempts.length);
      const requests = pending.slice(0, remainingCalls);
      return {
        schemaVersion: 1,
        action: "next",
        query,
        task,
        coverage,
        ...statusFromCoverage(coverage, false),
        requests: coverage.sufficient ? [] : requests,
        gaps: coverage.gaps,
        warnings,
        runManifest: manifest(attempts),
      };
    }

    const facets = decomposeQuery(query, task, options.maxSubqueries ?? 3);
    const delivery = evidenceCoverage(diverse, query, task, { asOf: effectiveAsOf });
    return hostResult(query, task, capabilities, attempts, diverse,
      { ...coverage, delivery: { sufficient: delivery.sufficient, gaps: delivery.gaps } },
      startedAt,
      { ...statusFromCoverage(coverage, false), facets, queryVariants: facetQueries(facets), warnings, runManifest: manifest(attempts) });
  }

  const { adapter, capabilities: explicitCapabilities } = await loadAdapter(options.adapter, options.capabilities, options);
  const capabilities = explicitCapabilities ?? normalizeCapabilities(
    await withTimeout(Promise.resolve(adapter.capabilities()), Math.max(1_000, deadlineAt - Date.now())),
  );
  requireRetrievalPath(capabilities);
  const output = await executeFusion(adapter, capabilities, task, query, { ...options, timeoutMs: budget.wallClockMs }, budget, deadlineAt, asOf);
  return {
    schemaVersion: 1,
    mode: "adapter-orchestrated",
    query,
    task,
    capabilities,
    ...output,
    citations: output.results.map((source, index) => `[${index + 1}] ${source.title ?? source.url} — ${source.citationUrl ?? source.url}`),
    providerAnswers: output.attempts.filter(result => result.answer).map(result => ({ provider: result.provider, answer: result.answer })),
    observability: {
      elapsedMs: Date.now() - startedAt,
      providerLatencyMs: Object.fromEntries(output.attempts.map(result => [providerAttemptKey(result), result.latencyMs])),
    },
    runManifest: manifest(output.attempts),
  };
}

export function usage() {
  return [
    "Usage: node scripts/search-fusion.mjs [options] <query>",
    "",
    "Options:",
    "  --adapter omp|host|<adapter>      Required unless --input, --capabilities or --plan is set",
    "  --capabilities <file>             Adapter capability JSON (for custom adapters)",
    "  --adapter direct                  Standalone REST adapter (env-key providers + keyless duckduckgo)",
    "  --providers a,b                   Restrict direct adapter to these providers",
    "  --doctor                          First-run auth check: per-provider status + setup instructions",
    "  --doctor --live                   Also fire one minimal request per ready provider",
    "  --login antigravity|gemini-cli    Pull a Google OAuth token for gemini grounding; stored in ~/.search-fusion/auth.json",
    "  --logout <provider>               Remove the stored OAuth token",
    "  --auth-mode auto|key|oauth        Credential preference for --adapter direct (auto = key first)",
    "  --input <file>                    Host-orchestrated search result JSON",
    "  --replay <file>                   Alias for --input",
    "  --plan                            Emit planned requests without executing",
    "  --next                            With --input: emit remaining requests for uncovered gaps",
    "  --benchmark-profile <name>        search-api | research-system",
    "  --strict-provider-pin             Fail attempts whose actual provider differs from requested",
    "  --output <file>                   Write JSON output to a file",
    "  --task lookup|comparison|tutorial|exploratory|factual",
    "  --freshness evergreen|recent|live",
    "  --domain general|coding|academic|news|china",
    "  --depth quick|verify|deep",
    "  --recency day|week|month|year",
    "  --as-of <date>                    Freeze freshness evaluation at this date",
    "  --limit N                         Results per provider/query",
    "  --top N                           Final diversified source count",
    "  --provider-count N                Initial providers for breadth wave (max 4)",
    "  --max-subqueries N                Hard cap on query variants (max 4)",
    "  --max-search-calls N              Total underlying search calls (default 9; search-api profile 5)",
    "  --max-fallback-calls N            Fallback provider calls (default 2; search-api profile 0)",
    "  --per-call-timeout-ms N           Per-provider timeout (default 45000)",
    "  --timeout-ms N                    Global search budget (default: quick 90000, verify 150000, deep 180000)",
    "  --pretty                          Pretty-print JSON",
  ].join("\n");
}

export async function runCli(argv = process.argv.slice(2)) {
  try {
    const parsed = parseArgs(argv);
    if (parsed.help) {
      process.stdout.write(`${usage()}\n`);
      return;
    }
    if (parsed.options.login || parsed.options.logout) {
      const { OAUTH_CLIENTS, loginProvider, clearStoredToken, loadStoredToken } = await import("../core/oauth.mjs");
      const provider = parsed.options.login ?? parsed.options.logout;
      if (!OAUTH_CLIENTS[provider]) {
        process.stderr.write(`No auto-pullable OAuth client for "${provider}". Supported: ${Object.keys(OAUTH_CLIENTS).join(", ")}
`);
        process.exitCode = 1;
        return;
      }
      if (parsed.options.logout) {
        const had = clearStoredToken(provider);
        process.stdout.write(had ? `${provider} token removed.
` : `${provider} had no stored token.
`);
        return;
      }
      const result = await loginProvider(provider);
      process.stdout.write(result.success
        ? `${provider} login OK${result.email ? ` (${result.email})` : ""}; token stored in ~/.search-fusion/auth.json
`
        : `${provider} login failed: ${result.error}
`);
      if (!result.success) process.exitCode = 1;
      return;
    }
    if (parsed.options.doctor) {
      const auth = await import("../core/provider-auth.mjs");
      const liveResults = parsed.options.live ? await auth.probeReadyProviders() : null;
      process.stdout.write(`${auth.renderDoctorReport(undefined, liveResults)}\n`);
      return;
    }
    const output = await runSearchFusion(parsed.query, parsed.options);
    const json = JSON.stringify(output, null, parsed.options.pretty ? 2 : 0);
    if (parsed.options.output) {
      await import("node:fs/promises").then(fs => fs.writeFile(path.resolve(parsed.options.output), `${json}\n`, "utf8"));
    }
    process.stdout.write(`${json}\n`);
  } catch (error) {
    process.stderr.write(`${sanitizeError(error)}\n`);
    if (sanitizeError(error).includes("deadline exceeded")) {
      process.exit(1);
    }
    process.exitCode = 1;
  }
}

const selfPath = fileURLToPath(import.meta.url);
if (path.resolve(process.argv[1] ?? "") === selfPath) await runCli();
