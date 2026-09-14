// Direct adapter: standalone REST calls to search provider APIs.
//
// Credentials come exclusively from environment variables declared in
// config/provider-auth.json — the skill never stores, reads or logs key
// values, so this adapter works on a fresh machine with zero harness
// integration. duckduckgo is keyless and always available.
import { PROVIDER_ENDPOINTS, detectProviderAuth } from "../core/provider-auth.mjs";
import { defaultAutoOrder, defaultProviderRoles, defaultRankSemantics, defaultRetrievalFamilies } from "../core/capabilities.mjs";

// Optional proxy: Node's built-in fetch ignores HTTPS_PROXY on Node < 24, and
// setGlobalDispatcher from a separately-installed undici does NOT affect the
// built-in instance (distinct module copies). When a proxy is configured and
// undici is resolvable (e.g. `npm i -g undici` with NODE_PATH at the global
// root — ESM import() ignores NODE_PATH, hence createRequire), use undici's
// own fetch bound to a ProxyAgent; otherwise stay on direct connections.
let activeFetch = globalThis.fetch;
const proxyUrl = process.env.HTTPS_PROXY ?? process.env.https_proxy ?? process.env.HTTP_PROXY ?? process.env.http_proxy;
if (proxyUrl) {
  try {
    const { createRequire } = await import("node:module");
    const nodeRequire = createRequire(import.meta.url);
    const undici = nodeRequire("undici");
    undici.setGlobalDispatcher(new undici.ProxyAgent(proxyUrl));
    activeFetch = undici.fetch;
  } catch {
    // undici not resolvable — stay on direct connections.
  }
}

const DEFAULT_LIMIT = 8;
const REQUEST_TIMEOUT_MS = 30000;

function classifyHttpFailure(provider, status, text) {
  const snippet = String(text ?? "").slice(0, 200);
  if (status === 401 || status === 403) {
    const err = new Error(`${provider} auth failed (${status}): check the provider's environment key. ${snippet}`);
    err.searchFusionType = "auth";
    return err;
  }
  if (status === 429) {
    const err = new Error(`${provider} rate limited (429). ${snippet}`);
    err.searchFusionType = "rate_limit";
    return err;
  }
  const err = new Error(`${provider} API error (${status}): ${snippet}`);
  err.searchFusionType = "provider";
  return err;
}

async function fetchJson(provider, url, init, signal, fetchImpl) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);
  try {
    const response = await (fetchImpl ?? activeFetch)(url, { ...init, signal: controller.signal });
    const text = await response.text();
    if (!response.ok) throw classifyHttpFailure(provider, response.status, text);
    try {
      return JSON.parse(text);
    } catch {
      const err = new Error(`${provider} returned non-JSON payload: ${text.slice(0, 120)}`);
      err.searchFusionType = "provider";
      throw err;
    }
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

function isoDaysAgo(days) {
  return new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
}

const RECENCY_DAYS = { day: 1, week: 7, month: 30, year: 365, live: 7, recent: 90 };

// --- per-provider request builders + response mappers (key-based) ---

function searchExa(apiKey, request) {
  const body = { query: request.query, numResults: request.limit ?? DEFAULT_LIMIT, type: "auto" };
  if (request.recency && RECENCY_DAYS[request.recency]) {
    body.startPublishedDate = isoDaysAgo(RECENCY_DAYS[request.recency]);
  }
  return fetchJson("exa", PROVIDER_ENDPOINTS.exa.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": apiKey },
    body: JSON.stringify(body),
  }, request.signal, request.fetch).then(payload => ({
    provider: "exa",
    sources: (payload.results ?? []).filter(r => r?.url).map(r => ({
      url: r.url,
      title: r.title ?? r.url,
      snippet: r.text ?? undefined,
      publishedAt: r.publishedDate ?? undefined,
    })),
    answer: undefined,
    metadata: { authMode: "env-key" },
  }));
}

function searchTavily(apiKey, request) {
  const body = { query: request.query, search_depth: "basic", max_results: request.limit ?? DEFAULT_LIMIT, include_answer: "advanced" };
  if (request.recency && RECENCY_DAYS[request.recency]) body.time_range = request.recency;
  return fetchJson("tavily", PROVIDER_ENDPOINTS.tavily.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify(body),
  }, request.signal, request.fetch).then(payload => ({
    provider: "tavily",
    sources: (payload.results ?? []).filter(r => r?.url).map(r => ({
      url: r.url,
      title: r.title ?? r.url,
      snippet: r.content ?? undefined,
      publishedAt: r.published_date ?? undefined,
    })),
    answer: typeof payload.answer === "string" ? payload.answer : undefined,
    metadata: { authMode: "env-key" },
  }));
}

function searchBrave(apiKey, request) {
  const params = new URLSearchParams({ q: request.query, count: String(request.limit ?? DEFAULT_LIMIT) });
  if (request.recency === "day") params.set("freshness", "pd");
  else if (request.recency === "week") params.set("freshness", "pw");
  else if (request.recency === "month") params.set("freshness", "pm");
  else if (request.recency === "year") params.set("freshness", "py");
  return fetchJson("brave", `${PROVIDER_ENDPOINTS.brave.url}?${params}`, {
    method: "GET",
    headers: { Accept: "application/json", "X-Subscription-Token": apiKey },
  }, request.signal, request.fetch).then(payload => ({
    provider: "brave",
    sources: (payload.web?.results ?? []).filter(r => r?.url).map(r => ({
      url: r.url,
      title: r.title ?? r.url,
      snippet: r.description ?? undefined,
      publishedAt: r.page_age ?? undefined,
    })),
    answer: payload.answer ?? undefined,
    metadata: { authMode: "env-key" },
  }));
}

function searchJina(apiKey, request) {
  const params = new URLSearchParams({ q: request.query });
  return fetchJson("jina", `${PROVIDER_ENDPOINTS.jina.url}?${params}`, {
    method: "GET",
    headers: { Accept: "application/json", Authorization: `Bearer ${apiKey}` },
  }, request.signal, request.fetch).then(payload => ({
    provider: "jina",
    sources: (payload.data ?? []).filter(r => r?.url).map(r => ({
      url: r.url,
      title: r.title ?? r.url,
      snippet: (r.content ?? r.description ?? "").slice(0, 400) || undefined,
      publishedAt: r.date ?? undefined,
    })),
    answer: undefined,
    metadata: { authMode: "env-key" },
  }));
}

function searchFirecrawl(apiKey, request) {
  const body = { query: request.query, limit: request.limit ?? DEFAULT_LIMIT };
  if (request.recency && RECENCY_DAYS[request.recency]) body.tbs = `qdr:${request.recency[0]}`;
  return fetchJson("firecrawl", PROVIDER_ENDPOINTS.firecrawl.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify(body),
  }, request.signal, request.fetch).then(payload => ({
    provider: "firecrawl",
    sources: (payload.data?.web ?? payload.data ?? []).filter(r => r?.url).map(r => ({
      url: r.url,
      title: r.title ?? r.url,
      snippet: r.description ?? r.markdown?.slice(0, 300) ?? undefined,
      publishedAt: r.publishedDate ?? undefined,
    })),
    answer: undefined,
    metadata: { authMode: "env-key" },
  }));
}

// --- keyless: DuckDuckGo HTML (best-effort, anti-bot sensitive) ---

function decodeDdgHref(href) {
  try {
    const url = new URL(href, "https://html.duckduckgo.com");
    const target = url.searchParams.get("uddg") ?? url.href;
    return decodeURIComponent(target);
  } catch {
    return href;
  }
}

async function searchDuckDuckGo(_apiKey, request) {
  const body = new URLSearchParams({ q: request.query, kl: "wt-wt" });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let html;
  try {
    const response = await activeFetch(`${PROVIDER_ENDPOINTS.duckduckgo.url}?${new URLSearchParams({ q: request.query })}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Referer: "https://html.duckduckgo.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) search-fusion/0.2",
      },
      signal: controller.signal,
    });
    html = await response.text();
    if (!response.ok) throw classifyHttpFailure("duckduckgo", response.status, html);
  } finally {
    clearTimeout(timer);
  }
  // Anchor extraction only: result__a links, DDG click-through uddg param decoded.
  const results = [];
  const anchorRe = /<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
  let match;
  while ((match = anchorRe.exec(html)) && results.length < (request.limit ?? DEFAULT_LIMIT)) {
    const url = decodeDdgHref(match[1]);
    if (!/^https?:/.test(url)) continue;
    const title = match[2].replace(/<[^>]+>/g, "").trim();
    results.push({ url, title: title || url });
  }
  const response = { provider: "duckduckgo", sources: results, answer: undefined, metadata: { authMode: "keyless" } };
  if (results.length === 0 && /anomaly|captcha|challenge/i.test(html)) {
    const err = new Error("duckduckgo keyless search blocked by anti-bot challenge; configure an env-key provider instead");
    err.searchFusionType = "provider";
    throw err;
  }
  return response;
}

const DIRECT_SEARCH = {
  exa: searchExa,
  tavily: searchTavily,
  brave: searchBrave,
  jina: searchJina,
  firecrawl: searchFirecrawl,
  duckduckgo: searchDuckDuckGo,
};

export function createDirectAdapter({ providers, env = process.env, fetchImpl } = {}) {
  const capable = Object.keys(DIRECT_SEARCH);
  const explicit = providers?.length ? [...new Set(providers)] : null;
  const available = (explicit ?? capable).filter(id => {
    if (!capable.includes(id)) return false;
    const status = detectProviderAuth(id, env).status;
    return status === "ready" || status === "keyless";
  });
  let fetchOverride = fetchImpl;
  const callSearch = (id, key, request) => {
    if (fetchOverride && id !== "duckduckgo") {
      // Test seam: route the per-provider builders through a mock transport.
      return DIRECT_SEARCH[id].call(null, key, { ...request, fetch: fetchOverride });
    }
    return DIRECT_SEARCH[id].call(null, key, request);
  };
  return {
    name: "direct",
    capabilities: async () => ({
      harness: "direct",
      level: available.length > 1 ? "L3" : available.length === 1 ? "L1" : "L0",
      providerPin: true,
      parallelSearch: true,
      structuredSources: true,
      fetch: false,
      providers: available,
      autoOrder: defaultAutoOrder(available),
      roles: defaultProviderRoles(available),
      rankSemantics: defaultRankSemantics(available),
      retrievalFamilies: defaultRetrievalFamilies(available),
      metadata: { adapter: "direct", authRegistry: "config/provider-auth.json", availableProviders: available },
    }),
    search: async request => {
      const id = request.provider;
      if (!DIRECT_SEARCH[id]) throw new Error(`direct adapter does not implement provider: ${id}`);
      const detection = detectProviderAuth(id, env);
      if (detection.status === "missing") {
        const err = new Error(`${id} has no configured credential; run --doctor for setup instructions`);
        err.searchFusionType = "auth";
        throw err;
      }
      const envKey = detection.modes?.find(mode => mode.type === "env" && mode.present)?.var;
      const key = envKey ? env[envKey] : undefined;
      return callSearch(id, key, request);
    },
    __setFetchForTests: impl => { fetchOverride = impl; },
  };
}
