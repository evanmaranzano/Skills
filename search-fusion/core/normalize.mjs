const TRACKING_PREFIXES = ["utm_"];
const TRACKING_KEYS = new Set(["fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "dclid"]);

function isRouteFragment(hash) {
  return typeof hash === "string" && hash.startsWith("#/");
}

function canonicalize(rawUrl, { stripWww, stripTrailingSlash, keepFragment }) {
  try {
    const url = new URL(String(rawUrl));
    url.protocol = url.protocol.toLowerCase();
    url.hostname = url.hostname.toLowerCase();
    if (stripWww) url.hostname = url.hostname.replace(/^www\./, "");
    if ((url.protocol === "https:" && url.port === "443") || (url.protocol === "http:" && url.port === "80")) url.port = "";
    for (const key of [...url.searchParams.keys()]) {
      const lower = key.toLowerCase();
      if (TRACKING_KEYS.has(lower) || TRACKING_PREFIXES.some(prefix => lower.startsWith(prefix))) url.searchParams.delete(key);
    }
    url.searchParams.sort();
    if (stripTrailingSlash) url.pathname = url.pathname.replace(/\/+$/, "") || "/";
    if (!keepFragment && !isRouteFragment(url.hash)) url.hash = "";
    return url.toString();
  } catch {
    let text = String(rawUrl ?? "");
    if (!keepFragment && !isRouteFragment(text.match(/#.*$/)?.[0])) text = text.replace(/#.*$/, "");
    if (stripTrailingSlash) text = text.replace(/\/+$/, "");
    return text;
  }
}

export function strictCanonicalUrl(rawUrl) {
  return canonicalize(rawUrl, { stripWww: false, stripTrailingSlash: false, keepFragment: true });
}

export function looseCanonicalUrl(rawUrl) {
  return canonicalize(rawUrl, { stripWww: true, stripTrailingSlash: true, keepFragment: false });
}

export function normalizeUrl(rawUrl) {
  return looseCanonicalUrl(rawUrl);
}

export function hostnameOf(rawUrl) {
  try {
    return new URL(rawUrl).hostname.toLowerCase().replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function isHttpUrl(rawUrl) {
  try {
    const protocol = new URL(rawUrl).protocol.toLowerCase();
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

export function normalizeSource(source = {}) {
  const originalUrl = String(source.url ?? "").trim();
  const valid = isHttpUrl(originalUrl);
  return {
    ...source,
    title: source.title ?? originalUrl,
    url: valid ? looseCanonicalUrl(originalUrl) : "",
    strictUrl: valid ? strictCanonicalUrl(originalUrl) : "",
    looseUrl: valid ? looseCanonicalUrl(originalUrl) : "",
    citationUrl: originalUrl,
    hostname: valid ? hostnameOf(originalUrl) : "",
    snippet: source.snippet ?? source.description ?? "",
    publishedAt: source.publishedAt ?? source.publishedDate ?? source.date,
  };
}
