import { hostnameOf } from "./normalize.mjs";
import { loadJson } from "./load-config.mjs";

const CONFIG = loadJson("../config/source-provenance.json", import.meta.url);
const ROLE_SCORES = CONFIG.scores ?? { unknown: 0.4 };
const HOST_SUFFIXES = CONFIG.hostSuffixes ?? {};
const URL_HINTS = CONFIG.urlHints ?? {};

function hostMatches(hostname, domain) {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

const COMMUNITY_PREFIX = /^(?:community|forums?|discuss|bbs|meta|comments)\./;

function pathnameOf(url) {
  try {
    return new URL(url).pathname.toLowerCase();
  } catch {
    return "";
  }
}

export function classifyProvenance(url) {
  const hostname = hostnameOf(url);
  if (!hostname) return "unknown";
  if (COMMUNITY_PREFIX.test(hostname)) return "community";

  for (const [role, domains] of Object.entries(HOST_SUFFIXES)) {
    if ((domains ?? []).some(domain => hostMatches(hostname, domain))) return role;
  }

  const haystack = `${hostname}${pathnameOf(url)}`;
  for (const [role, hints] of Object.entries(URL_HINTS)) {
    if ((hints ?? []).some(hint => haystack.includes(hint))) return role;
  }

  return "unknown";
}

export function provenanceScore(url) {
  return ROLE_SCORES[classifyProvenance(url)] ?? ROLE_SCORES.unknown ?? 0.4;
}
