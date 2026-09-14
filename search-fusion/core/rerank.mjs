const ROLE_PRIORITY = {
  primary_standard: 7,
  primary_paper: 6,
  primary_code: 6,
  code: 6,
  primary_official: 5,
  official_docs: 5,
  independent_benchmark: 4,
  news_reporting: 3,
  community: 2,
  aggregator: 1,
  unknown: 0,
};

export function diversifySources(sources, { top = 8, perDomain = 2 } = {}) {
  const selected = [];
  const domainCounts = new Map();
  const roleSeen = new Set();
  const remaining = [...sources];

  for (const source of remaining) {
    const domain = source.hostname ?? "";
    const role = source.provenance ?? "unknown";
    if ((domainCounts.get(domain) ?? 0) >= perDomain) continue;
    if (!roleSeen.has(role) || ROLE_PRIORITY[role] >= 4 || selected.length < Math.min(3, top)) {
      selected.push(source);
      domainCounts.set(domain, (domainCounts.get(domain) ?? 0) + 1);
      roleSeen.add(role);
    }
    if (selected.length >= top) return selected;
  }

  for (const source of remaining) {
    if (selected.includes(source)) continue;
    const domain = source.hostname ?? "";
    if ((domainCounts.get(domain) ?? 0) >= perDomain) continue;
    selected.push(source);
    domainCounts.set(domain, (domainCounts.get(domain) ?? 0) + 1);
    if (selected.length >= top) break;
  }

  return selected;
}
