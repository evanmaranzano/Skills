// Direct adapter: standalone REST calls to search provider APIs.
//
// Credentials come from environment variables or locally-stored OAuth tokens
// (declared in config/provider-auth.json, tokens in ~/.search-fusion/auth.json)
// — the skill never stores, reads or logs secret values, so this adapter works
// on a fresh machine with zero harness integration. Users choose per run with
// --auth-mode key|oauth|auto (auto = env key first, then OAuth). duckduckgo is
// keyless and always available.
import { PROVIDER_ENDPOINTS, detectProviderAuth, resolveCredential } from "../core/provider-auth.mjs";
import { ensureFreshAccessToken } from "../core/oauth.mjs";
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
    const err = new Error(`${provider} auth failed (${status}): check the provider's environment key or run --login again. ${snippet}`);
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

// --- per-provider request builders + response mappers ---
// Each builder receives (credential, request) where credential is
// { kind: "env-key" | "oauth" | "keyless", value } — kind decides the auth
// header style, so the same provider works under --auth-mode key or oauth.

function searchExa(credential, request) {
  const body = { query: request.query, numResults: request.limit ?? DEFAULT_LIMIT, type: "auto" };
  if (request.recency && RECENCY_DAYS[request.recency]) {
    body.startPublishedDate = isoDaysAgo(RECENCY_DAYS[request.recency]);
  }
  return fetchJson("exa", PROVIDER_ENDPOINTS.exa.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": credential.value },
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
    metadata: { authMode: credential.kind },
  }));
}

function searchTavily(credential, request) {
  const body = { query: request.query, search_depth: "basic", max_results: request.limit ?? DEFAULT_LIMIT, include_answer: "advanced" };
  if (request.recency && RECENCY_DAYS[request.recency]) body.time_range = request.recency;
  return fetchJson("tavily", PROVIDER_ENDPOINTS.tavily.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${credential.value}` },
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
    metadata: { authMode: credential.kind },
  }));
}

function searchBrave(credential, request) {
  const params = new URLSearchParams({ q: request.query, count: String(request.limit ?? DEFAULT_LIMIT) });
  if (request.recency === "day") params.set("freshness", "pd");
  else if (request.recency === "week") params.set("freshness", "pw");
  else if (request.recency === "month") params.set("freshness", "pm");
  else if (request.recency === "year") params.set("freshness", "py");
  return fetchJson("brave", `${PROVIDER_ENDPOINTS.brave.url}?${params}`, {
    method: "GET",
    headers: { Accept: "application/json", "X-Subscription-Token": credential.value },
  }, request.signal, request.fetch).then(payload => ({
    provider: "brave",
    sources: (payload.web?.results ?? []).filter(r => r?.url).map(r => ({
      url: r.url,
      title: r.title ?? r.url,
      snippet: r.description ?? undefined,
      publishedAt: r.page_age ?? undefined,
    })),
    answer: payload.answer ?? undefined,
    metadata: { authMode: credential.kind },
  }));
}

function searchJina(credential, request) {
  const params = new URLSearchParams({ q: request.query });
  return fetchJson("jina", `${PROVIDER_ENDPOINTS.jina.url}?${params}`, {
    method: "GET",
    headers: { Accept: "application/json", Authorization: `Bearer ${credential.value}` },
  }, request.signal, request.fetch).then(payload => ({
    provider: "jina",
    sources: (payload.data ?? []).filter(r => r?.url).map(r => ({
      url: r.url,
      title: r.title ?? r.url,
      snippet: (r.content ?? r.description ?? "").slice(0, 400) || undefined,
      publishedAt: r.date ?? undefined,
    })),
    answer: undefined,
    metadata: { authMode: credential.kind },
  }));
}

function searchFirecrawl(credential, request) {
  const body = { query: request.query, limit: request.limit ?? DEFAULT_LIMIT };
  if (request.recency && RECENCY_DAYS[request.recency]) body.tbs = `qdr:${request.recency[0]}`;
  return fetchJson("firecrawl", PROVIDER_ENDPOINTS.firecrawl.url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${credential.value}` },
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
    metadata: { authMode: credential.kind },
  }));
}

// Gemini grounding search, two transports:
// - env API key -> generativelanguage generateContent (x-goog-api-key)
// - OAuth (antigravity / gemini-cli login) -> Cloud Code Assist
//   v1internal:streamGenerateContent (SSE) with the companion projectId.
function parseCodeAssistSse(text) {
  let answer = "";
  const chunks = [];
  const queries = [];
  for (const line of String(text).split("\n")) {
    if (!line.startsWith("data:")) continue;
    const raw = line.slice(5).trim();
    if (!raw || raw === "[DONE]") continue;
    try {
      const payload = JSON.parse(raw);
      const candidate = payload.candidates?.[0] ?? {};
      for (const part of candidate.content?.parts ?? []) {
        if (typeof part.text === "string") answer += part.text;
      }
      const grounding = candidate.groundingMetadata ?? {};
      for (const chunk of grounding.groundingChunks ?? []) {
        if (chunk?.web?.uri) chunks.push(chunk.web);
      }
      for (const q of grounding.webSearchQueries ?? []) if (q) queries.push(q);
    } catch {
      // Partial SSE frame mid-stream; a later frame carries the payload.
    }
  }
  return { answer: answer.trim(), chunks, queries };
}

async function searchGeminiOauth(credential, request) {
  const { OAUTH_CLIENTS } = await import("../core/oauth.mjs");
  const client = OAUTH_CLIENTS[credential.oauthSource];
  if (!client?.codeAssist) throw new Error("gemini oauth source has no Code Assist definition");
  const base = client.codeAssist;
  const endpoints = base.sandboxEndpoint ? [base.endpoint, base.sandboxEndpoint] : [base.endpoint];
  const model = process.env.GEMINI_SEARCH_MODEL ?? "gemini-2.5-flash";
  const body = {
    project: credential.projectId,
    model,
    request: {
      contents: [{ role: "user", parts: [{ text: request.query }] }],
      tools: [{ google_search: {} }],
    },
  };
  if (base.requestType) {
    body.requestType = base.requestType;
    body.userAgent = "antigravity";
    body.requestId = `agent-${Date.now()}`;
  }
  let lastError;
  for (let index = 0; index < endpoints.length; index += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await (request.fetch ?? activeFetch)(`${endpoints[index]}/v1internal:streamGenerateContent?alt=sse`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${credential.value}`,
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          "User-Agent": base.userAgent,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const text = await response.text();
      if (!response.ok) throw classifyHttpFailure("gemini", response.status, text);
      const parsed = parseCodeAssistSse(text);
      return {
        provider: "gemini",
        sources: parsed.chunks
          .map(web => ({ url: web.uri, title: web.title ?? web.uri, snippet: web.domain ?? undefined }))
          .slice(0, request.limit ?? DEFAULT_LIMIT),
        answer: parsed.answer || undefined,
        citations: parsed.queries,
        metadata: { authMode: "oauth", oauthSource: credential.oauthSource, model },
      };
    } catch (error) {
      lastError = error;
      if (index < endpoints.length - 1) continue;
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastError ?? new Error("gemini oauth search failed");
}

function searchGemini(credential, request) {
  if (credential.kind === "oauth") return searchGeminiOauth(credential, request);
  const model = process.env.GEMINI_SEARCH_MODEL ?? "gemini-2.5-flash";
  const body = {
    contents: [{ parts: [{ text: request.query }] }],
    tools: [{ google_search: {} }],
  };
  return fetchJson("gemini", PROVIDER_ENDPOINTS.gemini.url + "/" + model + ":generateContent", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": credential.value },
    body: JSON.stringify(body),
  }, request.signal, request.fetch).then(payload => {
    const candidate = payload.candidates?.[0] ?? {};
    const answer = (candidate.content?.parts ?? [])
      .map(part => (typeof part.text === "string" ? part.text : ""))
      .join("")
      .trim() || undefined;
    const chunks = candidate.groundingMetadata?.groundingChunks ?? [];
    return {
      provider: "gemini",
      sources: chunks
        .map(chunk => chunk?.web)
        .filter(web => web?.uri)
        .map(web => ({ url: web.uri, title: web.title ?? web.uri, snippet: web.domain ?? undefined }))
        .slice(0, request.limit ?? DEFAULT_LIMIT),
      answer,
      citations: (candidate.groundingMetadata?.webSearchQueries ?? []).filter(Boolean),
      metadata: { authMode: credential.kind, model },
    };
  });
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

async function searchDuckDuckGo(credential, request) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let html;
  try {
    const response = await (request.fetch ?? activeFetch)(`${PROVIDER_ENDPOINTS.duckduckgo.url}?${new URLSearchParams({ q: request.query })}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Referer: "https://html.duckduckgo.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) search-fusion/0.4",
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
  gemini: searchGemini,
  duckduckgo: searchDuckDuckGo,
};

export function createDirectAdapter({ providers, env = process.env, fetchImpl, authMode = "auto", home = undefined } = {}) {
  const capable = Object.keys(DIRECT_SEARCH);
  const explicit = providers?.length ? [...new Set(providers)] : null;
  const available = (explicit ?? capable).filter(id => {
    if (!capable.includes(id)) return false;
    const status = detectProviderAuth(id, env, home).status;
    return status === "ready" || status === "keyless";
  });
  let fetchOverride = fetchImpl;

  const obtainCredential = async id => {
    const credential = resolveCredential(id, authMode, env, home);
    if (credential.kind === "oauth") {
      const source = credential.source;
      const token = await ensureFreshAccessToken(source, home, activeFetch);
      if (!token?.access_token) {
        const err = new Error(`${id} OAuth token could not be refreshed; run --login ${source ?? id} again`);
        err.searchFusionType = "auth";
        throw err;
      }
      if (!token.projectId) {
        const err = new Error(`${id} OAuth credential has no Code Assist projectId; run --login ${source} again`);
        err.searchFusionType = "auth";
        throw err;
      }
      return { kind: "oauth", value: token.access_token, oauthSource: source, projectId: token.projectId };
    }
    if (credential.kind === "env-key") return { kind: "env-key", value: credential.value };
    if (credential.kind === "keyless") return { kind: "keyless" };
    const err = new Error(`${id} has no configured credential; run --doctor for setup instructions`);
    err.searchFusionType = "auth";
    throw err;
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
      metadata: { adapter: "direct", authMode, authRegistry: "config/provider-auth.json", availableProviders: available },
    }),
    search: async request => {
      const id = request.provider;
      if (!DIRECT_SEARCH[id]) throw new Error(`direct adapter does not implement provider: ${id}`);
      const credential = await obtainCredential(id);
      const builder = DIRECT_SEARCH[id];
      if (fetchOverride) {
        // Test seam: route the per-provider builders through a mock transport.
        return builder(credential, { ...request, fetch: fetchOverride });
      }
      return builder(credential, request);
    },
    __setFetchForTests: impl => { fetchOverride = impl; },
  };
}
