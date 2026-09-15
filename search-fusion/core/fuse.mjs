import { normalizeSource } from "./normalize.mjs";
import { classifyProvenance, provenanceScore } from "./provenance.mjs";

const RANKED_K = 60;
const CITATION_K = 120;
const BASE = 1 / (RANKED_K + 1);
const FUTURE_DATE_SCORE = 0.3;

export const SCORE_PROFILES = {
  default: { rrf: 0.62, provenance: 0.18, freshness: 0.14, relevance: 0.06 },
  live: { rrf: 0.46, provenance: 0.14, freshness: 0.34, relevance: 0.06 },
  recent: { rrf: 0.52, provenance: 0.16, freshness: 0.26, relevance: 0.06 },
  academic: { rrf: 0.52, provenance: 0.3, freshness: 0.1, relevance: 0.08 },
  primary: { rrf: 0.56, provenance: 0.24, freshness: 0.12, relevance: 0.08 },
};

// Final-score weights follow the intent: time-sensitive queries reward dated
// evidence, academic/lookup queries reward primary provenance instead.
export function scoreProfileFor(intent = {}) {
  if (intent.freshness === "live") return { name: "live", weights: SCORE_PROFILES.live };
  if (intent.freshness === "recent") return { name: "recent", weights: SCORE_PROFILES.recent };
  const domains = intent.domainTags?.length ? intent.domainTags : [intent.domain];
  if (domains.includes("academic")) return { name: "academic", weights: SCORE_PROFILES.academic };
  if (intent.task === "factual" || intent.task === "tutorial") return { name: "primary", weights: SCORE_PROFILES.primary };
  return { name: "default", weights: SCORE_PROFILES.default };
}

function decay(rank, semantics) {
  if (semantics === "unknown") return BASE;
  const k = semantics === "citation-order" ? CITATION_K : RANKED_K;
  return BASE * (k + 1) / (k + rank + 1);
}

function freshnessFromAge(days) {
  if (days <= 1) return 1;
  if (days <= 7) return 0.9;
  if (days <= 30) return 0.7;
  if (days <= 90) return 0.5;
  if (days <= 365) return 0.3;
  return 0.1;
}

export function freshnessScore(source, freshnessNeed = "evergreen", asOf = Date.now()) {
  if (Number.isFinite(source.ageSeconds)) {
    if (source.ageSeconds < 0) return FUTURE_DATE_SCORE;
    return freshnessFromAge(source.ageSeconds / 86400);
  }
  const raw = String(source.publishedAt ?? source.publishedDate ?? "").trim();
  if (raw) {
    const relative = raw.match(/(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago/i);
    if (relative) {
      const amount = Number(relative[1]);
      const unit = relative[2].toLowerCase();
      const dayCount = { second: 1 / 86400, minute: 1 / 1440, hour: 1 / 24, day: 1, week: 7, month: 30, year: 365 }[unit] ?? 365;
      return freshnessFromAge(amount * dayCount);
    }
    if (/today|昨天|今天/i.test(raw)) return 1;
    const timestamp = Date.parse(raw);
    if (!Number.isNaN(timestamp)) {
      const ageDays = (asOf - timestamp) / 86400000;
      if (ageDays < 0) return FUTURE_DATE_SCORE;
      return freshnessFromAge(ageDays);
    }
  }
  return freshnessNeed === "recent" || freshnessNeed === "live" ? 0.2 : 0.5;
}

function cjkBigrams(text) {
  const runs = String(text).match(/[㐀-鿿豈-﫿]+/g) ?? [];
  const grams = [];
  for (const run of runs) {
    if (run.length === 1) grams.push(run);
    for (let index = 0; index < run.length - 1; index += 1) grams.push(run.slice(index, index + 2));
  }
  return grams;
}

export function relevanceScore(source, query) {
  const text = `${source.title ?? ""} ${source.snippet ?? ""}`.toLowerCase();
  const words = [...new Set(query.toLowerCase().match(/[\p{L}\p{N}][\p{L}\p{N}_-]*/gu) ?? [])]
    .map(term => term.trim())
    .filter(term => term.length > 2 && !/^[㐀-鿿豈-﫿]+$/.test(term));
  const grams = [...new Set(cjkBigrams(query.toLowerCase()))];
  const terms = [...words, ...grams];
  if (terms.length === 0) return 0.5;
  const hits = terms.filter(term => text.includes(term)).length;
  return hits / terms.length;
}

function rankSemanticsFor(capabilities, provider) {
  return capabilities?.rankSemantics?.[provider] ?? "unknown";
}

function familyOf(provider, capabilities = {}) {
  return capabilities?.retrievalFamilies?.[provider] ?? provider;
}

function newerDate(left, right) {
  if (!left) return right ?? null;
  if (!right) return left;
  const leftTime = Date.parse(left);
  const rightTime = Date.parse(right);
  if (Number.isNaN(leftTime)) return right;
  if (Number.isNaN(rightTime)) return left;
  return rightTime >= leftTime ? right : left;
}

export function fuseProviderResults(providerResults, query, intent = { freshness: "evergreen" }, capabilities = {}) {
  const asOf = Number.isFinite(intent.asOf) ? intent.asOf : Date.now();
  const groups = new Map();
  const familyUrlBestContribution = new Map();
  for (const result of providerResults) {
    if (result.ok === false) continue;
    const sources = Array.isArray(result.sources) ? result.sources : [];
    const family = familyOf(result.provider, capabilities);
    sources.forEach((rawSource, rank) => {
      const source = normalizeSource(rawSource);
      if (!source.url) return;
      const existing = groups.get(source.url) ?? {
        ...source,
        providers: [],
        families: [],
        providerSupport: 0,
        familySupport: 0,
        rrf: 0,
      };
      existing.providers = [...new Set([...existing.providers, result.provider])];
      existing.families = [...new Set([...existing.families, family])];
      existing.providerSupport = existing.providers.length;
      existing.familySupport = existing.families.length;
      if ((source.snippet ?? "").length > (existing.snippet ?? "").length) existing.snippet = source.snippet ?? "";
      const mergedDate = newerDate(existing.publishedAt, source.publishedAt);
      if (mergedDate) existing.publishedAt = mergedDate;
      if (!Number.isFinite(existing.ageSeconds) && Number.isFinite(source.ageSeconds)) existing.ageSeconds = source.ageSeconds;
      const contribution = decay(rank, rankSemanticsFor(capabilities, result.provider));
      const contributionKey = `${family}::${source.url}`;
      const previousBest = familyUrlBestContribution.get(contributionKey) ?? 0;
      if (contribution > previousBest) {
        familyUrlBestContribution.set(contributionKey, contribution);
        existing.rrf += contribution - previousBest;
      }
      groups.set(source.url, existing);
    });
  }

  const successfulProviders = new Set(
    providerResults
      .filter(result => result.ok !== false && (result.sources ?? []).length > 0)
      .map(result => result.provider)
      .filter(Boolean),
  );
  const successfulFamilies = new Set(
    [...successfulProviders].map(provider => familyOf(provider, capabilities)),
  );
  const maxRrf = Math.max(...[...groups.values()].map(source => source.rrf), 0.000001);
  const { weights } = scoreProfileFor(intent);
  const fused = [...groups.values()].map(source => {
    const provenance = classifyProvenance(source.url);
    const freshness = freshnessScore(source, intent.freshness, asOf);
    const provenanceValue = provenanceScore(source.url);
    const relevance = relevanceScore(source, query);
    const rrfNormalized = source.rrf / maxRrf;
    const score = weights.rrf * rrfNormalized + weights.provenance * provenanceValue + weights.freshness * freshness + weights.relevance * relevance;
    return {
      ...source,
      provenance,
      rrfNormalized: Number(rrfNormalized.toFixed(6)),
      freshnessScore: Number(freshness.toFixed(4)),
      provenanceScore: Number(provenanceValue.toFixed(4)),
      relevanceScore: Number(relevance.toFixed(4)),
      providerSupportRatio: successfulProviders.size > 0
        ? Number((source.providerSupport / successfulProviders.size).toFixed(4))
        : 0,
      familySupportRatio: successfulFamilies.size > 0
        ? Number((source.familySupport / successfulFamilies.size).toFixed(4))
        : 0,
      score: Number(score.toFixed(6)),
    };
  });

  fused.sort((left, right) => right.score - left.score || left.url.localeCompare(right.url));
  return fused;
}
