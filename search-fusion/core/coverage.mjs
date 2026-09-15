const PRIMARY_PROVENANCE = ["primary_official", "primary_code", "primary_paper", "primary_standard", "code"];

const FRESHNESS_WINDOWS_DAYS = { live: 7, recent: 90 };

export function coveragePolicy(intent = {}) {
  const task = intent.task ?? "factual";
  const freshness = intent.freshness ?? "evergreen";
  const depth = intent.depth ?? "verify";
  const base = {
    minUniqueCanonicalUrls: task === "comparison" || task === "exploratory" ? 6 : 4,
    minUniqueDomains: task === "comparison" || freshness === "live" ? 3 : 2,
    minPrimarySources: ["factual", "tutorial"].includes(task) ? 1 : 0,
  };
  // Coverage thresholds scale with depth: quick stops early, deep keeps
  // gathering instead of declaring victory on a thin candidate pool.
  if (depth === "quick") {
    return {
      minUniqueCanonicalUrls: Math.max(3, base.minUniqueCanonicalUrls - 2),
      minUniqueDomains: Math.max(1, base.minUniqueDomains - 1),
      minPrimarySources: base.minPrimarySources,
    };
  }
  if (depth === "deep") {
    return {
      minUniqueCanonicalUrls: base.minUniqueCanonicalUrls + 2,
      minUniqueDomains: base.minUniqueDomains + 1,
      minPrimarySources: base.minPrimarySources > 0 ? base.minPrimarySources + 1 : 0,
    };
  }
  return base;
}

function cleanEntity(text) {
  return String(text ?? "")
    .replace(/^(?:横评|对比|比较|评测|测评|分析|调研|研究|看看|说一下?|谈谈|compare|comparison of|review)\s+/iu, "")
    .replace(/\s*(?:的)?(?:最新|当前|现状|怎么样|如何|哪个好|区别|差异|对比|测评|评测).*$/u, "")
    .replace(/\s+(?:latest|current|newest|comparison|compared|review|reviews)\b.*$/iu, "")
    .trim();
}

// Supports two-entity ("A vs B", "A 和 B") and multi-entity comparisons
// ("A vs B vs C", "A、B 和 C"); capped at 4 entities.
export function extractComparisonEntities(query) {
  const text = String(query ?? "").trim();
  if (!text) return [];
  const parts = text
    .split(/\s+vs\.?\s+|\s+versus\s+|\s*、\s*|\s+和\s+|\s+与\s+|\s+跟\s+|\s+and\s+/iu)
    .map(cleanEntity)
    .filter(name => name.length > 0 && name.length <= 40);
  const unique = [...new Set(parts)];
  if (unique.length >= 2) return unique.slice(0, 4);
  return [];
}

export function requiredFacetsFor(query, task = {}) {
  const facets = [];
  const windowDays = FRESHNESS_WINDOWS_DAYS[task.freshness];
  if (task.task === "comparison") {
    for (const entity of extractComparisonEntities(query)) {
      // Time-sensitive comparisons require *per-entity* dated evidence, not
      // just any fresh source somewhere in the pool.
      facets.push({ id: `entity:${entity}`, kind: "entity", entity, ...(windowDays ? { windowDays } : {}) });
    }
  }
  if (windowDays) facets.push({ id: "freshness", kind: "freshness", windowDays });
  return facets;
}

function relevantSources(groupedSources) {
  return groupedSources.filter(source => (source.relevanceScore ?? 0.5) > 0);
}

function normalizeEntityText(text) {
  return String(text ?? "").toLowerCase().replace(/[\s\-_.·・]+/g, "");
}

// Substring match plus a punctuation-insensitive variant so "GPT-5" still
// matches "GPT5" and "Claude Code" matches "claude-code".
export function sourceMatchesEntity(source, entity) {
  const haystack = `${source.title ?? ""} ${source.snippet ?? ""}`.toLowerCase();
  if (haystack.includes(entity.toLowerCase())) return true;
  const compactNeedle = normalizeEntityText(entity);
  if (!compactNeedle) return false;
  return normalizeEntityText(haystack).includes(compactNeedle);
}

function sourceDateDays(source, asOf) {
  if (Number.isFinite(source.ageSeconds)) return source.ageSeconds / 86400;
  const raw = String(source.publishedAt ?? source.publishedDate ?? "").trim();
  if (!raw) return null;
  const timestamp = Date.parse(raw);
  if (Number.isNaN(timestamp)) return null;
  return (asOf - timestamp) / 86400000;
}

export function retrievalCoverage(groupedSources, providerResults = [], intent = {}) {
  const relevant = relevantSources(groupedSources);
  const domains = new Set(relevant.map(source => source.hostname).filter(Boolean));
  const families = new Set(relevant.flatMap(source => source.families ?? []));
  const primary = relevant.filter(source => PRIMARY_PROVENANCE.includes(source.provenance));
  const policy = coveragePolicy(intent);
  const successfulAttempts = providerResults.filter(result => result.ok && (result.sources ?? []).length > 0);
  const sufficient = relevant.length >= policy.minUniqueCanonicalUrls
    && domains.size >= policy.minUniqueDomains
    && primary.length >= policy.minPrimarySources;
  return {
    uniqueCanonicalUrls: relevant.length,
    totalSources: groupedSources.length,
    offTopicSources: groupedSources.length - relevant.length,
    uniqueDomains: domains.size,
    uniqueFamilies: families.size,
    primarySources: primary.length,
    successfulAttempts: successfulAttempts.length,
    successfulProviders: new Set(successfulAttempts.map(result => result.provider).filter(Boolean)).size,
    policy,
    sufficient,
  };
}

export function evidenceCoverage(groupedSources, query, task = {}, options = {}) {
  const asOf = Number.isFinite(options.asOf) ? options.asOf : Date.now();
  const pool = relevantSources(groupedSources);
  const required = requiredFacetsFor(query, task);
  const statuses = [];
  const gaps = [];

  for (const facet of required) {
    if (facet.kind === "entity") {
      const covered = pool.some(source => {
        if (!sourceMatchesEntity(source, facet.entity)) return false;
        if (!facet.windowDays) return true;
        const days = sourceDateDays(source, asOf);
        return days !== null && days >= 0 && days <= facet.windowDays;
      });
      statuses.push({ ...facet, status: covered ? "covered" : "pending" });
      if (!covered) {
        gaps.push(facet.windowDays
          ? `missing dated evidence about "${facet.entity}" within ${facet.windowDays}d window`
          : `missing evidence about "${facet.entity}"`);
      }
    }
    if (facet.kind === "freshness") {
      const fresh = pool.some(source => {
        const days = sourceDateDays(source, asOf);
        return days !== null && days >= 0 && days <= facet.windowDays;
      });
      statuses.push({ ...facet, status: fresh ? "covered" : "pending" });
      if (!fresh) gaps.push(`no dated source within ${facet.windowDays}d window for ${task.freshness} need`);
    }
  }

  return {
    requiredFacets: statuses,
    offTopicSources: groupedSources.length - pool.length,
    sufficient: statuses.every(facet => facet.status === "covered"),
    gaps,
  };
}

export function combinedCoverage(groupedSources, providerResults, query, intent = {}, options = {}) {
  const retrieval = retrievalCoverage(groupedSources, providerResults, intent);
  const evidence = evidenceCoverage(groupedSources, query, intent, options);
  const gaps = [...evidence.gaps];
  if (!retrieval.sufficient) gaps.unshift("retrieval pool below policy minimums");
  return {
    retrieval,
    evidence,
    gaps,
    sufficient: retrieval.sufficient && evidence.sufficient,
  };
}
