import { extractComparisonEntities } from "./coverage.mjs";

function uniqueFacets(facets) {
  const seen = new Set();
  const out = [];
  for (const facet of facets) {
    const query = String(facet.query ?? "").trim();
    if (!query || seen.has(query)) continue;
    seen.add(query);
    out.push({
      id: facet.id,
      query,
      purpose: facet.purpose ?? "broad-recall",
      requiredRoles: [...new Set(facet.requiredRoles ?? [])],
      required: Boolean(facet.required),
      entities: facet.entities ?? [],
    });
  }
  return out;
}

function comparisonFacets(query) {
  const entities = extractComparisonEntities(query);
  if (entities.length < 2) {
    return [
      { id: "comparison", query: `${query} comparison`, purpose: "comparison", requiredRoles: ["semantic"], required: true },
      { id: "recent", query: `${query} latest`, purpose: "freshness", requiredRoles: ["fresh"] },
    ];
  }
  const [left, right] = entities;
  return [
    { id: "left", query: `${left} capabilities`, purpose: "comparison-left", requiredRoles: ["semantic"], required: true, entities: [left] },
    { id: "right", query: `${right} capabilities`, purpose: "comparison-right", requiredRoles: ["semantic"], required: true, entities: [right] },
    { id: "recent", query: `${left} vs ${right} latest comparison`, purpose: "freshness", requiredRoles: ["fresh"], entities: [left, right] },
  ];
}

export function decomposeQuery(query, task = { task: "exploratory", freshness: "evergreen", domain: "general", depth: "quick" }, maxQueries = 3) {
  const facets = [{ id: "base", query, purpose: "broad-recall", requiredRoles: [], required: true }];
  if (task.depth === "quick") return uniqueFacets(facets).slice(0, 1);

  if (task.task === "comparison") facets.push(...comparisonFacets(query));
  const domains = task.domainTags?.length ? task.domainTags : [task.domain];
  if (domains.includes("coding")) {
    facets.push({ id: "official", query: `${query} documentation source code`, purpose: "primary-source", requiredRoles: ["developer"] });
  }
  if (domains.includes("academic")) {
    facets.push({ id: "paper", query: `${query} paper benchmark arxiv`, purpose: "primary-source", requiredRoles: ["academic"] });
  }
  if (domains.includes("china")) {
    facets.push({ id: "official-zh", query: `${query} 最新 官方`, purpose: "primary-source", requiredRoles: ["china"] });
  }
  if (task.freshness === "recent" || task.freshness === "live") {
    facets.push({ id: "freshness", query: `${query} latest update`, purpose: "freshness", requiredRoles: ["fresh"], required: true });
  }
  if (task.task === "tutorial") {
    facets.push({ id: "guide", query: `${query} official guide`, purpose: "primary-source", requiredRoles: ["developer"] });
  }
  if (task.task === "exploratory") {
    facets.push({ id: "overview", query: `${query} overview`, purpose: "broad-recall", requiredRoles: ["general"] });
    facets.push({ id: "criticism", query: `${query} limitations criticism`, purpose: "counterpoint", requiredRoles: ["general"] });
  }

  const unique = uniqueFacets(facets);
  const required = unique.filter(facet => facet.required);
  const optional = unique.filter(facet => !facet.required);
  // maxSubqueries is a hard budget: required facets are kept first, then the
  // plan is truncated exactly at the cap. Uncovered required dimensions are
  // surfaced later through evidence coverage gaps instead of hidden overflow.
  return [...required, ...optional].slice(0, Math.max(1, maxQueries));
}

export function facetQueries(facets = []) {
  return facets.map(facet => (typeof facet === "string" ? facet : facet.query)).filter(Boolean);
}
