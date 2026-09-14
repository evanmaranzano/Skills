import { loadJson } from "./load-config.mjs";

const DEFAULTS = loadJson("../config/provider-defaults.json", import.meta.url);
const DEFAULT_ROLES = DEFAULTS.roles ?? {};
const DEFAULT_RANK_SEMANTICS = DEFAULTS.rankSemantics ?? {};
const DEFAULT_RETRIEVAL_FAMILIES = DEFAULTS.retrievalFamilies ?? {};
const PREFERRED_ORDER = DEFAULTS.autoOrder ?? [];

export function defaultProviderRoles(providers = []) {
  const result = {};
  for (const provider of providers) {
    result[provider] = [...(DEFAULT_ROLES[provider] ?? ["general"])];
  }
  return result;
}

export function defaultRankSemantics(providers = []) {
  const result = {};
  for (const provider of providers) {
    result[provider] = DEFAULT_RANK_SEMANTICS[provider] ?? "unknown";
  }
  return result;
}

export function defaultRetrievalFamilies(providers = []) {
  const result = {};
  for (const provider of providers) {
    result[provider] = DEFAULT_RETRIEVAL_FAMILIES[provider] ?? provider;
  }
  return result;
}

export function defaultAutoOrder(providers = []) {
  const ordered = PREFERRED_ORDER.filter(provider => providers.includes(provider));
  const rest = providers.filter(provider => !ordered.includes(provider));
  return [...ordered, ...rest];
}

export function roleCandidates(roles = {}) {
  const result = {};
  for (const [provider, providerRoles] of Object.entries(roles)) {
    for (const role of providerRoles) {
      if (!result[role]) result[role] = [];
      result[role].push(provider);
    }
  }
  return result;
}
