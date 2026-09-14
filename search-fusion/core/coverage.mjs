const PRIMARY_PROVENANCE = ["primary_official", "primary_code", "primary_paper", "primary_standard", "code"];

const FRESHNESS_WINDOWS_DAYS = { live: 7, recent: 90 };

function coveragePolicy(intent = {}) {
  const task = intent.task ?? "factual";
  const freshness = intent.freshness ?? "evergreen";
  return {
    minUniqueCanonicalUrls: task === "comparison" || task === "exploratory" ? 6 : 4,
    minUniqueDomains: task === "comparison" || freshness === "live" ? 3 : 2,
    minPrimarySources: ["factual", "tutorial"].includes(task) ? 1 : 0,
  };
}

export function extractComparisonEntities(query) {
  const match = String(query ?? "").match(/^(.+?)\s*(?:vs\.?|versus|和|与|跟)\s*(.+?)\s*$/i);
  if (!match) return [];
  const cleanLeft = match[1].replace(/^(?:横评|对比|比较|评测|测评|分析|调研|研究|看看|说一下?|谈谈|compare|comparison of|review)\s+/iu, "").trim();
  const cleanRight = match[2]
    .replace(/\s*(?:的)?(?:最新|当前|现状|怎么样|如何|哪个好|区别|差异|对比|测评|评测).*$/u, "")
    .replace(/\s+(?:latest|current|newest|comparison|compared|review|reviews)\b.*$/iu, "")
    .trim();
  return [cleanLeft, cleanRight].filter(name => name.length > 0 && name.length <= 40);
}

export function requiredFacetsFor(query, task = {}) {
  const facets = [];
  if (task.task === "comparison") {
    for (const entity of extractComparisonEntities(query)) {
      facets.push({ id: `entity:${entity}`, kind: "entity", entity });
    }
  }
  const windowDays = FRESHNESS_WINDOWS_DAYS[task.freshness];
  if (windowDays) facets.push({ id: "freshness", kind: "freshness", windowDays });
  return facets;
}

function relevantSources(groupedSources) {
  return groupedSources.filter(source => (source.relevanceScore ?? 0.5) > 0);
}

function sourceMatchesEntity(source, entity) {
  const haystack = `${source.title ?? ""} ${source.snippet ?? ""}`.toLowerCase();
  return haystack.includes(entity.toLowerCase());
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
      const covered = pool.some(source => sourceMatchesEntity(source, facet.entity));
      statuses.push({ ...facet, status: covered ? "covered" : "pending" });
      if (!covered) gaps.push(`missing evidence about "${facet.entity}"`);
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
