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
  const timeoutMs = provider === "xai" ? 60000 : REQUEST_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeoutMs);
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

import { randomUUID } from "node:crypto";

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

function asText(value) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function searchTinyfish(credential, request) {
  const url = new URL(PROVIDER_ENDPOINTS.tinyfish.url);
  url.searchParams.set("query", request.query);
  url.searchParams.set("num_results", String(Math.min(request.limit ?? DEFAULT_LIMIT, 20)));
  const recencyMinutes = { day: 1440, week: 10080, month: 43200, year: 525600 }[request.recency];
  if (recencyMinutes) url.searchParams.set("recency_minutes", String(recencyMinutes));
  return fetchJson("tinyfish", url, {
    method: "GET",
    headers: { Accept: "application/json", "X-API-Key": credential.value },
  }, request.signal, request.fetch).then(payload => ({
    provider: "tinyfish",
    sources: (payload.results ?? []).filter(result => result?.url).map(result => ({
      url: result.url,
      title: asText(result.title) ?? asText(result.site_name) ?? result.url,
      snippet: asText(result.snippet),
      author: asText(result.site_name),
    })),
    answer: undefined,
    metadata: { authMode: credential.kind },
  }));
}

function parseZaiMcpPayload(text) {
  const messages = [];
  for (const line of String(text).split("\n")) {
    const data = line.trim().startsWith("data:") ? line.trim().slice(5).trim() : "";
    if (!data) continue;
    try { messages.push(JSON.parse(data)); } catch { /* ignore non-JSON SSE frames */ }
  }
  if (messages.length) return messages[messages.length - 1];
  try { return JSON.parse(text); } catch { return null; }
}

async function postZaiMcp(apiKey, method, params, sessionId, request, expectResponse) {
  const headers = {
    Authorization: `Bearer ${apiKey}`,
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  if (sessionId) headers["Mcp-Session-Id"] = sessionId;
  const body = { jsonrpc: "2.0", method, params };
  if (expectResponse) body.id = randomUUID();
  const response = await (request.fetch ?? activeFetch)(PROVIDER_ENDPOINTS.zai.url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: request.signal,
  });
  const responseText = await response.text();
  if (!response.ok) throw classifyHttpFailure("zai", response.status, responseText);
  return {
    sessionId: response.headers.get("Mcp-Session-Id") ?? sessionId,
    payload: expectResponse ? parseZaiMcpPayload(responseText) : undefined,
  };
}

function unwrapZaiResult(value) {
  const candidates = [value, value?.structuredContent, value?.data, value?.result];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) return candidate;
    if (candidate && Array.isArray(candidate.search_result)) return candidate.search_result;
    if (candidate && Array.isArray(candidate.results)) return candidate.results;
    if (candidate && Array.isArray(candidate.content)) {
      for (const part of candidate.content) {
        const text = asText(part?.text);
        if (!text) continue;
        try {
          const parsed = JSON.parse(text);
          const nested = unwrapZaiResult(parsed);
          if (nested.length) return nested;
        } catch { /* answer text, not a structured result */ }
      }
    }
  }
  return [];
}

async function searchZai(credential, request) {
  const init = await postZaiMcp(credential.value, "initialize", {
    protocolVersion: "2025-03-26",
    capabilities: {},
    clientInfo: { name: "search-fusion", version: "0.1.0" },
  }, undefined, request, true);
  const initialized = init.payload;
  if (initialized?.error) throw classifyHttpFailure("zai", 400, initialized.error.message);
  await postZaiMcp(credential.value, "notifications/initialized", {}, init.sessionId, request, false);
  const call = await postZaiMcp(credential.value, "tools/call", {
    name: "web_search_prime",
    arguments: { search_query: request.query, count: request.limit ?? DEFAULT_LIMIT },
  }, init.sessionId, request, true);
  const rpc = call.payload;
  if (rpc?.error) throw classifyHttpFailure("zai", 400, rpc.error.message);
  const result = rpc?.result ?? rpc;
  if (result?.isError) {
    const message = (result.content ?? []).map(part => asText(part?.text)).filter(Boolean).join("\n");
    throw classifyHttpFailure("zai", 400, message || "Z.AI MCP tool call failed");
  }
  const sources = unwrapZaiResult(result).filter(item => item?.link || item?.url).map(item => ({
    url: item.link ?? item.url,
    title: asText(item.title) ?? item.link ?? item.url,
    snippet: asText(item.content),
    publishedAt: asText(item.publish_date) ?? asText(item.publishedDate),
    author: asText(item.media),
  }));
  return { provider: "zai", sources, answer: undefined, metadata: { authMode: credential.kind } };
}

function searchKimi(credential, request) {
  return fetchJson("kimi", PROVIDER_ENDPOINTS.kimi.url, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json", Authorization: `Bearer ${credential.value}` },
    body: JSON.stringify({
      text_query: request.query,
      limit: Math.min(request.limit ?? DEFAULT_LIMIT, 20),
      enable_page_crawling: false,
      timeout_seconds: 30,
    }),
  }, request.signal, request.fetch).then(payload => ({
    provider: "kimi",
    sources: (payload.search_results ?? []).filter(result => result?.url).map(result => ({
      url: result.url,
      title: asText(result.title) ?? result.url,
      snippet: asText(result.snippet) ?? asText(result.content),
      publishedAt: asText(result.date),
      author: asText(result.site_name),
    })),
    answer: undefined,
    metadata: { authMode: credential.kind },
  }));
}

function parseDataFrames(text) {
  const frames = [];
  for (const line of String(text).split("\n")) {
    if (!line.startsWith("data:")) continue;
    const data = line.slice(5).trim();
    if (!data || data === "[DONE]") continue;
    try { frames.push(JSON.parse(data)); } catch { /* tolerate split/non-JSON SSE frames */ }
  }
  return frames;
}

function searchXai(credential, request) {
  const baseUrl = (process.env.XAI_BASE_URL ?? "https://api.x.ai/v1").replace(/\/+$/, "");
  const body = {
    model: process.env.XAI_SEARCH_MODEL ?? "grok-4.5",
    input: [
      { role: "system", content: "You are a helpful assistant with web search capabilities. Search the web and cite sources." },
      { role: "user", content: request.query },
    ],
    tools: [{ type: "web_search" }],
    tool_choice: "required",
    reasoning: { effort: "low" },
  };
  return fetchJson("xai", `${baseUrl}/responses`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${credential.value}` },
    body: JSON.stringify(body),
  }, request.signal, request.fetch).then(payload => {
    const sources = [];
    const seen = new Set();
    const add = (url, title, snippet) => {
      if (!url || seen.has(url)) return;
      seen.add(url);
      sources.push({ url, title: asText(title) ?? url, snippet: asText(snippet) });
    };
    for (const item of payload.output ?? []) {
      if (item?.type === "web_search_call") {
        for (const group of [item.action?.sources, item.sources, item.results]) {
          for (const source of group ?? []) add(source.url ?? source.source_website_url, source.title ?? source.caption);
        }
      }
      for (const part of item?.content ?? []) {
        for (const annotation of part?.annotations ?? []) {
          if (annotation?.type === "url_citation") add(annotation.url, annotation.title, annotation.cited_text ?? annotation.text);
        }
      }
    }
    for (const url of payload.citations ?? []) if (typeof url === "string") add(url);
    const answer = asText(payload.output_text) ?? ((payload.output ?? [])
      .flatMap(item => item?.content ?? [])
      .map(part => asText(part?.text) ?? asText(part?.output_text))
      .filter(Boolean).join("\n") || undefined);
    return { provider: "xai", sources: sources.slice(0, request.limit ?? DEFAULT_LIMIT), answer, metadata: { authMode: credential.kind, model: payload.model, requestId: payload.id } };
  });
}

function codexAccountId(credential) {
  return credential.accountId ?? credential.chatgpt_account_id;
}

async function searchCodex(credential, request) {
  const baseUrl = (process.env.CODEX_BASE_URL ?? "https://chatgpt.com/backend-api").replace(/\/+$/, "");
  const headers = {
    Authorization: `Bearer ${credential.value}`,
    "OpenAI-Beta": "responses=experimental",
    originator: "search-fusion",
    version: "0.153.0",
    Accept: "text/event-stream",
    "Content-Type": "application/json",
  };
  const accountId = codexAccountId(credential);
  if (accountId) headers["chatgpt-account-id"] = accountId;
  const body = {
    model: process.env.CODEX_SEARCH_MODEL ?? "gpt-5.5",
    stream: true,
    store: false,
    include: ["web_search_call.action.sources"],
    parallel_tool_calls: true,
    input: [{ type: "message", role: "user", content: [{ type: "input_text", text: request.query }] }],
    tools: [{ type: "web_search", search_context_size: "high" }],
    tool_choice: { type: "web_search" },
    instructions: "You are a helpful assistant with web search capabilities. Search the web to answer accurately and cite sources.",
  };
  const response = await (request.fetch ?? activeFetch)(`${baseUrl}/codex/responses`, {
    method: "POST", headers, body: JSON.stringify(body), signal: request.signal,
  });
  const text = await response.text();
  if (!response.ok) throw classifyHttpFailure("codex", response.status, text);
  const sources = [];
  const seen = new Set();
  let answer = "";
  let model;
  let requestId;
  let invoked = false;
  for (const frame of parseDataFrames(text)) {
    const type = frame.type;
    if (typeof type === "string" && type.startsWith("response.web_search_call")) invoked = true;
    if (type === "response.created") {
      requestId = frame.response?.id ?? requestId;
      model = frame.response?.model ?? model;
    }
    if (type === "response.output_text.delta" && typeof frame.delta === "string") answer += frame.delta;
    if (type === "response.output_item.done") {
      const item = frame.item;
      if (item?.type === "web_search_call") {
        invoked = true;
        for (const group of [item.action?.sources, item.sources, item.results]) {
          for (const source of group ?? []) {
            const url = source.url ?? source.source_website_url;
            if (url && !seen.has(url)) { seen.add(url); sources.push({ url, title: source.title ?? source.caption ?? url }); }
          }
        }
      }
      if (item?.type === "message") {
        for (const part of item.content ?? []) {
          if (part?.type === "output_text" && typeof part.text === "string") {
            answer += answer ? `\n\n${part.text}` : part.text;
            for (const annotation of part.annotations ?? []) {
              if (annotation?.type === "url_citation" && annotation.url && !seen.has(annotation.url)) {
                seen.add(annotation.url); sources.push({ url: annotation.url, title: annotation.title ?? annotation.url });
              }
            }
          }
        }
      }
    }
    if (type === "response.completed" || type === "response.done") {
      requestId = frame.response?.id ?? requestId;
      model = frame.response?.model ?? model;
    }
    if (type === "error" || type === "response.failed") throw new Error(`Codex search failed: ${frame.error?.message ?? frame.response?.error?.message ?? "upstream error"}`);
  }
  if (!invoked) throw new Error("Codex returned a completion without running web search");
  return { provider: "codex", sources: sources.slice(0, request.limit ?? DEFAULT_LIMIT), answer: asText(answer), metadata: { authMode: credential.kind, model, requestId } };
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
  tinyfish: searchTinyfish,
  zai: searchZai,
  kimi: searchKimi,
  xai: searchXai,
  codex: searchCodex,
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
      const source = credential.source ?? id;
      const token = await ensureFreshAccessToken(source, home, activeFetch);
      if (!token?.access_token) {
        const err = new Error(`${id} OAuth token could not be refreshed; run --login ${source ?? id} again`);
        err.searchFusionType = "auth";
        throw err;
      }
      if (id === "gemini" && !token.projectId) {
        const err = new Error(`${id} OAuth credential has no Code Assist projectId; run --login ${source} again`);
        err.searchFusionType = "auth";
        throw err;
      }
      return {
        kind: "oauth",
        value: token.access_token,
        oauthSource: source,
        projectId: token.projectId,
        accountId: token.accountId,
      };
    }
    if (credential.kind === "env-key" || credential.kind === "env-token") {
      return { kind: credential.kind, value: credential.value };
    }
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
