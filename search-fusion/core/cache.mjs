import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, unlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const CACHE_TTLS = {
  evergreen: 7 * 24 * 3600_000,
  recent: 3600_000,
  live: 0,
};

export function cacheTtlFor(freshness = "evergreen") {
  return CACHE_TTLS[freshness] ?? CACHE_TTLS.evergreen;
}

export function cacheDir(home = os.homedir()) {
  return path.join(home, ".search-fusion", "cache");
}

export function searchCacheKey(provider, query) {
  const normalized = String(query ?? "").trim().toLowerCase().replace(/\s+/g, " ");
  return createHash("sha256").update(`${provider}::${normalized}`).digest("hex");
}

export async function readSearchCache(provider, query, { home, ttlMs, now = Date.now() } = {}) {
  if (!ttlMs) return null;
  try {
    const raw = await readFile(path.join(cacheDir(home), `${searchCacheKey(provider, query)}.json`), "utf8");
    const entry = JSON.parse(raw);
    if (!entry || typeof entry.storedAt !== "number" || !entry.response) return null;
    if (now - entry.storedAt > ttlMs) return null;
    return entry.response;
  } catch {
    return null;
  }
}

export async function writeSearchCache(provider, query, response, { home, now = Date.now() } = {}) {
  const dir = cacheDir(home);
  await mkdir(dir, { recursive: true });
  const payload = { version: 1, provider, query, storedAt: now, response };
  await writeFile(path.join(dir, `${searchCacheKey(provider, query)}.json`), JSON.stringify(payload), "utf8");
}

// Best-effort eviction of entries older than the longest TTL. Cheap enough to
// run on writes; failures are intentionally ignored.
export async function sweepSearchCache({ home, now = Date.now(), maxAgeMs = CACHE_TTLS.evergreen } = {}) {
  try {
    const dir = cacheDir(home);
    const files = await readdir(dir);
    await Promise.all(files.filter(file => file.endsWith(".json")).map(async file => {
      try {
        const raw = await readFile(path.join(dir, file), "utf8");
        const entry = JSON.parse(raw);
        if (typeof entry?.storedAt !== "number" || now - entry.storedAt > maxAgeMs) {
          await unlink(path.join(dir, file));
        }
      } catch {
        await unlink(path.join(dir, file)).catch(() => {});
      }
    }));
  } catch {
    // cache directory missing or unreadable: nothing to sweep
  }
}
