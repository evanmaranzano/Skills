import { defaultAutoOrder, defaultProviderRoles, defaultRankSemantics, defaultRetrievalFamilies } from "../core/capabilities.mjs";

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function normalizeHostSearchResult(provider, raw = {}) {
  const response = raw.details?.response ?? raw.response ?? raw.result ?? raw;
  const sources = asArray(response.sources).filter(source => source?.url).map(source => ({
    url: source.url,
    title: source.title,
    snippet: source.snippet,
    publishedAt: source.publishedAt ?? source.publishedDate ?? source.date,
    ageSeconds: source.ageSeconds,
    author: source.author,
  }));
  return {
    provider,
    sources,
    answer: response.answer,
    citations: asArray(response.citations).map(citation => citation?.url ?? citation).filter(Boolean),
    searchQueries: asArray(response.searchQueries),
    metadata: {
      model: response.model,
      authMode: response.authMode,
      usage: response.usage,
    },
  };
}

export function createHostAdapter({ search, fetch, providers = [], providerPin = true, harness = "host", capabilities = {} }) {
  if (typeof search !== "function") throw new Error("A host search function is required");
  const named = [...new Set(providers)].filter(Boolean);
  const genericHost = named.length === 0;
  const uniqueProviders = genericHost ? ["host"] : named;
  const pin = genericHost ? false : providerPin;
  return {
    name: harness,
    capabilities: async () => ({
      harness,
      level: pin ? "L3" : uniqueProviders.length > 1 ? "L2" : "L1",
      providerPin: pin,
      parallelSearch: capabilities.parallelSearch !== false,
      structuredSources: capabilities.structuredSources !== false,
      fetch: typeof fetch === "function" || capabilities.fetch === true,
      providers: uniqueProviders,
      autoOrder: capabilities.autoOrder ?? defaultAutoOrder(uniqueProviders),
      roles: capabilities.roles ?? defaultProviderRoles(uniqueProviders),
      rankSemantics: capabilities.rankSemantics ?? defaultRankSemantics(uniqueProviders),
      retrievalFamilies: capabilities.retrievalFamilies ?? defaultRetrievalFamilies(uniqueProviders),
      metadata: capabilities.metadata ?? {},
    }),
    search: async request => {
      const response = await search({
        query: request.query,
        provider: request.provider,
        recency: request.recency,
        limit: request.limit,
        signal: request.signal,
      });
      return normalizeHostSearchResult(request.provider ?? "host", response);
    },
    ...(typeof fetch === "function" ? { fetch } : {}),
  };
}
