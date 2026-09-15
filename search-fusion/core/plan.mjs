import { classifyQuery } from "./classify.mjs";
import { decomposeQuery, facetQueries } from "./decompose.mjs";
import { defaultProviderRoles, defaultRankSemantics, defaultRetrievalFamilies, roleCandidates } from "./capabilities.mjs";

function wantedRoles(task) {
  const roles = [];
  const domains = task.domainTags?.length ? task.domainTags : [task.domain];
  if (domains.includes("coding")) roles.push("semantic", "developer");
  if (domains.includes("academic")) roles.push("academic", "semantic");
  if (domains.includes("china")) roles.push("china", "general");
  if (task.freshness === "recent" || task.freshness === "live") roles.push("fresh");
  if (task.task === "tutorial") roles.push("developer", "general");
  if (task.task === "comparison") roles.push("semantic", "general", "fresh");
  if (task.task === "factual") roles.push("general", "semantic");
  roles.push("general");
  return [...new Set(roles)];
}

export function familyOf(provider, capabilities = {}) {
  return capabilities?.retrievalFamilies?.[provider] ?? provider;
}

export function selectProvidersByRole(task, capabilities, { count = 3, scores } = {}) {
  const roles = capabilities?.roles ?? defaultProviderRoles(capabilities?.providers ?? []);
  const byRole = roleCandidates(roles);
  const order = capabilities?.autoOrder ?? Object.keys(roles);
  const selected = [];
  const usedFamilies = new Set();
  const scoreOf = provider => scores?.[provider] ?? 0.5;
  const pickBest = eligible => [...eligible]
    .sort((left, right) => scoreOf(right) - scoreOf(left) || order.indexOf(left) - order.indexOf(right))[0];

  function take(provider) {
    if (!provider || selected.includes(provider)) return false;
    selected.push(provider);
    usedFamilies.add(familyOf(provider, capabilities));
    return selected.length >= count;
  }

  for (const role of wantedRoles(task)) {
    const candidates = byRole[role] ?? [];
    const eligible = order.filter(provider =>
      candidates.includes(provider)
      && !selected.includes(provider)
      && !usedFamilies.has(familyOf(provider, capabilities)));
    const candidate = pickBest(eligible);
    if (candidate && take(candidate)) return selected;
  }

  for (const provider of order) {
    if (selected.includes(provider) || usedFamilies.has(familyOf(provider, capabilities))) continue;
    if (take(provider)) return selected;
  }

  for (const provider of order) {
    if (take(provider)) break;
  }
  return selected;
}

export function providersForFacet(facet, capabilities, pool, { count = 1, exclude } = {}) {
  const roles = capabilities?.roles ?? {};
  const byRole = roleCandidates(roles);
  const order = (capabilities?.autoOrder ?? []).filter(provider => pool.includes(provider));
  const orderedPool = [...order, ...pool.filter(provider => !order.includes(provider))]
    .filter(provider => !exclude?.has(provider));
  if (!facet?.requiredRoles?.length) return orderedPool.slice(0, count);

  const picks = [];
  const usedFamilies = new Set();
  for (const role of facet.requiredRoles) {
    for (const provider of orderedPool) {
      if (!(byRole[role] ?? []).includes(provider) || picks.includes(provider)) continue;
      const family = familyOf(provider, capabilities);
      if (usedFamilies.has(family)) continue;
      picks.push(provider);
      usedFamilies.add(family);
      if (picks.length >= count) return picks;
    }
  }
  return picks.length > 0 ? picks : orderedPool.slice(0, count);
}

export function planSearchWaves({
  query,
  facets,
  selectedProviders = [],
  remainingProviders = [],
  capabilities = {},
  budget = {},
  scores,
} = {}) {
  const list = Array.isArray(facets) && facets.length
    ? facets
    : [{ id: "base", query, purpose: "broad-recall", requiredRoles: [] }];
  const base = list[0];
  const extra = list.slice(1);
  const maxCalls = budget.maxSearchCalls ?? 9;
  const maxFallbackCalls = budget.maxFallbackCalls ?? 2;
  const fallbackReserve = Math.min(
    maxFallbackCalls,
    remainingProviders.length,
    Math.max(0, maxCalls - Math.max(1, selectedProviders.length)),
  );

  const breadth = selectedProviders.map(provider => ({
    query: base.query,
    provider,
    facetId: base.id ?? "base",
    wave: "breadth",
  }));
  const facetAttempts = extra.flatMap(facet =>
    providersForFacet(facet, capabilities, selectedProviders, { count: 1 }).map(provider => ({
      query: facet.query,
      provider,
      facetId: facet.id,
      wave: "facet",
    })),
  );
  const fallbackOrder = scores
    ? [...remainingProviders].sort((left, right) => (scores[right] ?? 0.5) - (scores[left] ?? 0.5))
    : remainingProviders;
  const fallback = fallbackOrder.slice(0, maxFallbackCalls).map(provider => ({
    query,
    provider,
    facetId: "base",
    wave: "fallback",
  }));

  return { breadth, facets: facetAttempts, fallback, fallbackReserve, maxCalls };
}

export function inferCapabilityLevel(adapterCapabilities = {}) {
  const providers = adapterCapabilities.providers ?? [];
  if (providers.length === 0) return "L0";
  if (adapterCapabilities.providerPin) return "L3";
  if (providers.length > 1) return "L2";
  return "L1";
}

export async function mapSearchCalls(items, mapper, parallel = true) {
  if (parallel !== false) return Promise.all(items.map((item, index) => mapper(item, index)));
  const results = [];
  for (let index = 0; index < items.length; index += 1) {
    results.push(await mapper(items[index], index));
  }
  return results;
}

export function normalizeCapabilities(adapterCapabilities = {}) {
  const providers = adapterCapabilities.providers ?? [];
  const autoOrder = adapterCapabilities.autoOrder?.length ? adapterCapabilities.autoOrder : providers;
  const roles = adapterCapabilities.roles ?? defaultProviderRoles(providers);
  const rankSemantics = adapterCapabilities.rankSemantics ?? defaultRankSemantics(providers);
  const retrievalFamilies = adapterCapabilities.retrievalFamilies ?? defaultRetrievalFamilies(providers);
  return {
    harness: adapterCapabilities.harness ?? "unknown",
    level: inferCapabilityLevel({ ...adapterCapabilities, providers }),
    providerPin: Boolean(adapterCapabilities.providerPin),
    parallelSearch: adapterCapabilities.parallelSearch !== false,
    structuredSources: adapterCapabilities.structuredSources !== false,
    fetch: Boolean(adapterCapabilities.fetch),
    providers,
    autoOrder,
    roles,
    rankSemantics,
    retrievalFamilies,
    metadata: adapterCapabilities.metadata ?? {},
  };
}

export function planFusion(query, capabilities, options = {}) {
  const normalized = normalizeCapabilities(capabilities);
  const task = classifyQuery(query, options);
  const maxSubqueries = Math.max(1, Math.min(options.maxSubqueries ?? 3, 4));
  const facets = decomposeQuery(query, task, maxSubqueries);
  const queryVariants = facetQueries(facets);
  const providerCount = Math.max(1, Math.min(options.providerCount ?? 3, 4));
  const fusionMode = normalized.providerPin ? "provider-fusion" : normalized.providers.length > 1 ? "multi-tool-fusion" : "query-diversification";
  const providers = selectProvidersByRole(task, normalized, { count: providerCount });
  const remainingProviders = (normalized.autoOrder ?? normalized.providers).filter(provider => !providers.includes(provider));
  const waves = planSearchWaves({
    query,
    facets,
    selectedProviders: providers,
    remainingProviders,
    capabilities: normalized,
    budget: { maxSearchCalls: options.maxSearchCalls ?? 9, maxProviders: providerCount },
  });
  return { task, facets, queryVariants, providers, fusionMode, waves, capabilities: normalized };
}
