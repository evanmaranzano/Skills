import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

import { ambiguousAxes } from "./classify.mjs";
import { providerDescriptions } from "./capabilities.mjs";

const ALLOWED = {
  task: new Set(["comparison", "tutorial", "factual", "exploratory"]),
  freshness: new Set(["live", "recent", "evergreen"]),
  domain: new Set(["coding", "academic", "china", "news", "general"]),
  depth: new Set(["deep", "verify", "quick"]),
};

/** How many providers Jev may recommend; validated against the live catalog. */
export const PROVIDER_PICK_LIMIT = 4;

const QUESTIONS = {
  task: {
    type: "choice",
    instructions: "What kind of search task is this query?",
    criteria: {
      comparison: "Comparing two or more products, tools, papers, or options",
      tutorial: "How-to, setup, configuration, or implementation steps",
      factual: "Definition, official docs, or a closed what-is question",
      exploratory: "Open-ended research without a closed form",
    },
  },
  freshness: {
    type: "choice",
    instructions: "How time-sensitive is this query?",
    criteria: {
      live: "Breaking news or something happening right now (hours/days)",
      recent: "Latest status, current release, or recent developments (weeks/months)",
      evergreen: "Stable knowledge that does not depend on recency",
    },
  },
  domain: {
    type: "choice",
    instructions: "Which subject domain should retrieve sources?",
    criteria: {
      coding: "APIs, SDKs, programming, GitHub, deployment",
      academic: "Papers, benchmarks, algorithms, research models",
      china: "China-market products, Chinese platforms, domestic vendors",
      news: "Press, policy, markets, announcements",
      general: "None of the above",
    },
  },
  depth: {
    type: "choice",
    instructions: "How thorough should retrieval be?",
    criteria: {
      deep: "Multi-source investigation or a full comparison",
      verify: "Confirm a fact or check current status",
      quick: "A short lookup is enough",
    },
  },
};

export { QUESTIONS as AXIS_QUESTIONS };

/**
 * Compact capability catalog for fast routing decisions (Jev or a fallback
 * agent LLM): provider id, kind, roles, one-line description and reliability.
 * Kept intentionally small — one round trip, few hundred tokens.
 */
export function buildProviderCatalog(capabilities = {}, { scores } = {}) {
  const descriptions = providerDescriptions();
  const providers = capabilities.providers ?? [];
  const roles = capabilities.roles ?? {};
  const order = capabilities.autoOrder?.length ? capabilities.autoOrder : providers;
  const ordered = [...order.filter(id => providers.includes(id)), ...providers.filter(id => !order.includes(id))];
  return ordered.map(id => ({
    id,
    kind: id.startsWith("reach-") ? "platform" : "web",
    roles: [...(roles[id] ?? [])],
    description: descriptions[id] ?? null,
    reliability: Number.isFinite(scores?.[id]) ? Math.round(scores[id] * 100) / 100 : 0.5,
  }));
}

/**
 * The deployed Jev endpoint only accepts {model, state, questions} — extra
 * top-level fields are rejected 422 (live-verified). The catalog therefore
 * travels inside a `routing` question: criteria keys are provider ids, values
 * compress kind/roles/reliability/description. The answer's probabilities
 * distribution ranks the whole catalog in one round trip.
 */
export function routingQuestion(catalog = []) {
  const criteria = {};
  for (const entry of catalog) {
    criteria[entry.id] = [entry.kind, (entry.roles ?? []).join(","), `r=${entry.reliability}`, entry.description]
      .filter(part => part !== null && part !== "")
      .join("; ");
  }
  return {
    type: "choice",
    instructions: "Which search provider should run this query first? Judge by provider kind, roles, reliability and description versus the query's intent, language and platform.",
    criteria,
  };
}

/** Turn a routing answer into ranked picks: {id, weight} pairs, ids validated. */
function picksFromRoutingAnswer(answer, providerIds) {
  const known = new Set(providerIds ?? []);
  const probabilities = answer?.probabilities;
  const picks = [];
  if (probabilities && typeof probabilities === "object") {
    for (const [id, probability] of Object.entries(probabilities)) {
      const weight = Number(probability);
      if (!known.has(id) || !Number.isFinite(weight) || weight < 0.05) continue;
      picks.push({ id, weight: Math.round(weight * 1000) / 1000 });
    }
    picks.sort((left, right) => right.weight - left.weight);
  }
  if (!picks.length) {
    const choice = answer?.choice;
    if (typeof choice === "string" && known.has(choice)) picks.push({ id: choice, weight: 1 });
  }
  return picks.slice(0, PROVIDER_PICK_LIMIT);
}

// The Jev endpoint is intentionally NOT baked into this public repo: the base
// URL comes from env (SEARCH_FUSION_JEV_BASE_URL / TYPESAFE_BASE_URL) or
// ~/.omp/agent/.env. No URL configured → Jev stays off (fail-open to rules).
const DEFAULT_TIMEOUT_MS = 8_000;

let cachedFetch;

function parseEnvFile(text) {
  const out = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq <= 0) continue;
    const key = trimmed.slice(0, eq).trim();
    let value = trimmed.slice(eq + 1).trim();
    if (
      (value.startsWith("\"") && value.endsWith("\""))
      || (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

export function loadJevCredentials() {
  const fileVars = {};
  try {
    Object.assign(
      fileVars,
      parseEnvFile(readFileSync(path.join(os.homedir(), ".omp", "agent", ".env"), "utf8")),
    );
  } catch {
    // omp env is optional
  }
  const apiKey = process.env.SEARCH_FUSION_JEV_API_KEY
    || process.env.TYPESAFE_API_KEY
    || fileVars.TYPESAFE_API_KEY
    || "";
  const baseUrl = (
    process.env.SEARCH_FUSION_JEV_BASE_URL
    || process.env.TYPESAFE_BASE_URL
    || fileVars.TYPESAFE_BASE_URL
    || ""
  ).replace(/\/+$/, "");
  const model = process.env.TYPESAFE_DEFAULT_MODEL
    || fileVars.TYPESAFE_DEFAULT_MODEL
    || "jev-latest";
  return { apiKey, baseUrl, model };
}

export function jevEnabled(options = {}) {
  if (options.noJev) return false;
  if (options.benchmarkProfile) return false;
  const flag = process.env.SEARCH_FUSION_JEV;
  if (flag === "0" || /^(false|off|no)$/i.test(flag ?? "")) return false;
  return true;
}

async function proxiedFetch() {
  if (cachedFetch) return cachedFetch;
  const proxyUrl = process.env.HTTPS_PROXY
    ?? process.env.https_proxy
    ?? process.env.HTTP_PROXY
    ?? process.env.http_proxy;
  if (proxyUrl) {
    try {
      const undici = createRequire(import.meta.url)("undici");
      undici.setGlobalDispatcher(new undici.ProxyAgent(proxyUrl));
      cachedFetch = undici.fetch.bind(undici);
      return cachedFetch;
    } catch {
      // undici not resolvable — stay on direct connections
    }
  }
  cachedFetch = globalThis.fetch;
  return cachedFetch;
}

function redact(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message
    .replace(/(api[-_ ]?key|authorization|bearer|token|secret)([\s=:]+)[^\s,;]+/gi, "$1$2[redacted]")
    .slice(0, 240);
}

/**
 * Rule-first intent + routing. Only axes that hit catch-all regexes are sent
 * to Jev, together with the provider capability catalog (deps.catalog) so one
 * call can also return a ranked provider pick. Fail-open: timeout, missing
 * key, or invalid answers leave the rule values in place and callers fall
 * back to rules or the executing agent's own LLM choice.
 */
export async function refineIntentWithJev(query, intent, options = {}, deps = {}) {
  const axes = ambiguousAxes(query, options);
  if (!axes.length) return { intent, jev: { used: false, reason: "rules-confident" } };
  if (!jevEnabled(options)) return { intent, jev: { used: false, reason: "disabled", axes } };

  const credentials = deps.credentials ?? loadJevCredentials();
  if (!credentials.apiKey) return { intent, jev: { used: false, reason: "no-credential", axes } };
  if (!credentials.baseUrl) return { intent, jev: { used: false, reason: "no-endpoint", axes } };

  const questions = {};
  for (const axis of axes) questions[axis] = QUESTIONS[axis];
  const catalog = Array.isArray(deps.catalog) ? deps.catalog : null;
  const providerIds = deps.providerIds ?? (catalog ? catalog.map(entry => entry.id) : []);
  if (catalog?.length) questions.routing = routingQuestion(catalog);
  const fetchImpl = deps.fetch ?? await proxiedFetch();
  const timeoutMs = deps.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetchImpl(`${credentials.baseUrl}/v1/systemone`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${credentials.apiKey}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: credentials.model,
        state: query,
        questions,
      }),
      signal: controller.signal,
    });
    if (!response.ok) {
      return {
        intent,
        jev: { used: false, reason: "http", status: response.status, axes },
      };
    }
    const payload = await response.json();
    const answers = payload?.answers ?? {};
    const next = { ...intent };
    const applied = [];
    for (const axis of axes) {
      const choice = answers[axis]?.choice;
      if (ALLOWED[axis].has(choice)) {
        next[axis] = choice;
        applied.push(axis);
      }
    }
    if (applied.includes("domain") && next.domain !== "general" && !(next.domainTags ?? []).includes(next.domain)) {
      next.domainTags = [...(next.domainTags ?? []), next.domain];
    }
    const providers = catalog?.length ? picksFromRoutingAnswer(answers.routing, providerIds) : [];
    return {
      intent: next,
      providers: providers.length ? providers : undefined,
      jev: {
        used: applied.length > 0 || providers.length > 0,
        reason: applied.length || providers.length ? "applied" : "no-valid-answer",
        axes,
        applied,
        providers: providers.length ? providers : undefined,
        model: payload?.model ?? credentials.model,
      },
    };
  } catch (error) {
    const reason = error?.name === "AbortError" ? "timeout" : "error";
    return { intent, jev: { used: false, reason, axes, error: redact(error) } };
  } finally {
    clearTimeout(timer);
  }
}
