import { existsSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { defaultProviderRoles, defaultRankSemantics, defaultRetrievalFamilies } from "../core/capabilities.mjs";

// Mirrors OMP SEARCH_PROVIDER_ORDER (src/web/search/types.ts), minus "auto".
// This is a known-provider reference used for default ordering only — it is NOT
// an admission gate. Providers configured in webSearchOrder but absent here are
// still admitted (fail-open): core gives them a "general" role and "unknown"
// rank semantics until provider-defaults.json describes them.
// webSearchOrder config only sets priority: unlisted providers stay available.
const OMP_PROVIDER_ORDER = [
  "perplexity", "gemini", "anthropic", "codex", "xai", "zai", "exa",
  "tinyfish", "jina", "kagi", "tavily", "firecrawl", "brave", "kimi",
  "parallel", "synthetic", "searxng", "startpage", "duckduckgo", "ecosia",
  "google", "mojeek", "public",
];

let searchModulePromise;

function searchModuleCandidates() {
  const relative = path.join("@oh-my-pi", "pi-coding-agent", "src", "web", "search", "index.ts");
  const home = os.homedir();
  return [
    process.env.OMP_SEARCH_MODULE,
    path.join(home, "node_modules", relative),
    path.join(home, ".bun", "install", "global", "node_modules", relative),
    path.join(path.dirname(process.execPath), "node_modules", relative),
    path.join(path.dirname(process.execPath), "..", "node_modules", relative),
  ].filter(Boolean);
}

async function loadSearchModule() {
  searchModulePromise ??= (async () => {
    const candidate = searchModuleCandidates().find(item => existsSync(item));
    if (!candidate) throw new Error("Cannot locate OMP web-search module; set OMP_SEARCH_MODULE");
    // Compatibility adapter: OMP installs this module in different roots, so the path is runtime-selected.
    const module = await import(pathToFileURL(candidate).href);
    if (typeof module.runSearchQuery !== "function") throw new Error("OMP search module has no runSearchQuery export");
    return module;
  })();
  return searchModulePromise;
}

function readYamlList(text, key) {
  const match = text.match(new RegExp(`^\\s*${key}:\\s*\\n((?:\\s+- .+\\n)+)`, "m"));
  if (!match) return undefined;
  return [...match[1].matchAll(/^\s+- ([a-z0-9-]+)\s*$/gim)].map(item => item[1]);
}

function readOmpSearchSettings() {
  const configPath = path.join(os.homedir(), ".omp", "agent", "config.yml");
  try {
    const text = readFileSync(configPath, "utf8");
    return {
      preferred: readYamlList(text, "webSearchOrder"),
      excluded: readYamlList(text, "webSearchExclude") ?? [],
    };
  } catch {
    return { preferred: undefined, excluded: [] };
  }
}

function classifyFailure(message) {
  if (/authorization failed|\b401\b|\b403\b|unauthor|forbidden|api key/i.test(message)) return "auth";
  if (/rate.?limit|\b429\b/i.test(message)) return "rate_limit";
  if (/timeout|timed out|abort/i.test(message)) return "timeout";
  if (/network|econn|enotfound|fetch failed|socket|dns/i.test(message)) return "network";
  return "provider";
}

class OmpSearchError extends Error {
  constructor(message, type) {
    super(message);
    this.name = "OmpSearchError";
    this.searchFusionType = type;
  }
}

export function createOmpInternalAdapter() {
  const { preferred, excluded } = readOmpSearchSettings();
  const excludedSet = new Set(excluded ?? []);
  // Fail-open capability discovery: known providers minus exclusions, plus any
  // webSearchOrder entries the known-set mirror does not recognize yet.
  const availableProviders = [...new Set([
    ...OMP_PROVIDER_ORDER.filter(id => !excludedSet.has(id)),
    ...(preferred ?? []).filter(id => !excludedSet.has(id)),
  ])];
  const preferredValid = (preferred ?? []).filter(id => !excludedSet.has(id));
  const autoOrder = preferredValid.length
    ? [...preferredValid, ...availableProviders.filter(id => !preferredValid.includes(id))]
    : [...availableProviders];

  return {
    name: "omp",
    capabilities: async () => ({
      harness: "omp",
      level: availableProviders.length === 0 ? "L0" : "L3",
      providerPin: true,
      parallelSearch: true,
      structuredSources: true,
      fetch: false,
      providers: availableProviders,
      autoOrder,
      roles: defaultProviderRoles(availableProviders),
      rankSemantics: defaultRankSemantics(availableProviders),
      retrievalFamilies: defaultRetrievalFamilies(availableProviders),
      metadata: {
        adapter: "omp-internal",
        compatibility: true,
        availableProviders,
        preferredOrder: preferredValid,
        excludedProviders: [...excludedSet],
      },
    }),
    search: async request => {
      const module = await loadSearchModule();
      const result = await module.runSearchQuery({
        query: request.query,
        provider: request.provider ?? "auto",
        recency: request.recency,
        limit: request.limit,
        num_search_results: request.limit,
      }, { signal: request.signal });
      const details = result?.details ?? {};
      // OMP reports provider-chain failure as details.error WITHOUT throwing:
      // empty response.sources with provider "none" or the last tried provider.
      if (details.error) {
        throw new OmpSearchError(String(details.error), classifyFailure(String(details.error)));
      }
      const response = details.response ?? {};
      const actualProvider = response.provider && response.provider !== "none"
        ? response.provider
        : request.provider ?? "omp";
      return {
        provider: actualProvider,
        requestedProvider: request.provider ?? "auto",
        sources: (response.sources ?? []).filter(source => source?.url),
        answer: response.answer,
        citations: (response.citations ?? []).map(citation => citation?.url ?? citation).filter(Boolean),
        searchQueries: response.searchQueries ?? [],
        metadata: {
          model: response.model,
          authMode: response.authMode,
          requestId: response.requestId,
          usage: response.usage,
        },
      };
    },
  };
}
