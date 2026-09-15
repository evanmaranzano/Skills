import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

export const STATS_VERSION = 1;
const CONSECUTIVE_RESET_MS = 24 * 3600_000;
const DEMOTE_THRESHOLD = 0.35;

export function providerStatsPath(home = os.homedir()) {
  return path.join(home, ".search-fusion", "provider-stats.json");
}

export function emptyProviderStats() {
  return { version: STATS_VERSION, providers: {} };
}

export async function loadProviderStats(home) {
  try {
    const raw = await readFile(providerStatsPath(home), "utf8");
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || parsed.providers === null || typeof parsed.providers !== "object") {
      return emptyProviderStats();
    }
    return { version: STATS_VERSION, providers: parsed.providers };
  } catch {
    return emptyProviderStats();
  }
}

export async function saveProviderStats(stats, home) {
  const target = providerStatsPath(home);
  await mkdir(path.dirname(target), { recursive: true });
  const tmp = `${target}.tmp`;
  await writeFile(tmp, `${JSON.stringify(stats, null, 2)}\n`, "utf8");
  await rename(tmp, target);
}

export function recordAttempts(stats, attempts, { now = Date.now() } = {}) {
  const next = stats ?? emptyProviderStats();
  next.providers = next.providers ?? {};
  for (const attempt of attempts ?? []) {
    // fromCache hits are not real calls; provider_mismatch is a strict-pin
    // enforcement artifact, not a signal about the provider's health.
    if (!attempt?.provider || attempt.fromCache || attempt.errorType === "provider_mismatch") continue;
    const entry = next.providers[attempt.provider] ??= {
      calls: 0,
      failures: 0,
      rateLimits: 0,
      timeouts: 0,
      authFailures: 0,
      consecutiveFailures: 0,
      ewmaLatencyMs: null,
      lastErrorType: null,
      updatedAt: null,
    };
    entry.calls += 1;
    if (Number.isFinite(attempt.latencyMs)) {
      entry.ewmaLatencyMs = entry.ewmaLatencyMs === null
        ? Math.round(attempt.latencyMs)
        : Math.round(0.7 * entry.ewmaLatencyMs + 0.3 * attempt.latencyMs);
    }
    if (attempt.ok === false) {
      entry.failures += 1;
      entry.consecutiveFailures += 1;
      entry.lastErrorType = attempt.errorType ?? "provider";
      if (attempt.errorType === "rate_limit") entry.rateLimits += 1;
      if (attempt.errorType === "timeout") entry.timeouts += 1;
      if (attempt.errorType === "auth") entry.authFailures += 1;
    } else {
      entry.consecutiveFailures = 0;
    }
    entry.updatedAt = new Date(now).toISOString();
  }
  return next;
}

export function reliabilityScore(entry, { now = Date.now() } = {}) {
  if (!entry || !entry.calls) return 0.5;
  let score = 1 - entry.failures / entry.calls;
  const updatedAt = Date.parse(entry.updatedAt ?? "");
  const fresh = Number.isFinite(updatedAt) && now - updatedAt < CONSECUTIVE_RESET_MS;
  if (fresh && entry.consecutiveFailures >= 2) score *= 0.5;
  return Math.max(0, Math.min(1, Number(score.toFixed(4))));
}

export function reliabilityScores(providers, stats, options = {}) {
  return Object.fromEntries(
    (providers ?? []).map(provider => [provider, reliabilityScore(stats?.providers?.[provider], options)]),
  );
}

// Stable re-order: providers whose observed reliability is clearly bad sink to
// the end; scores within `tolerance` keep their static autoOrder position so
// the order does not flip-flop on tiny differences.
export function orderByReliability(providers, stats, { tolerance = 0.2, now = Date.now() } = {}) {
  const decorated = (providers ?? []).map((provider, index) => ({
    provider,
    index,
    score: reliabilityScore(stats?.providers?.[provider], { now }),
  }));
  const healthy = decorated.filter(item => item.score >= DEMOTE_THRESHOLD);
  const unhealthy = decorated.filter(item => item.score < DEMOTE_THRESHOLD);
  healthy.sort((left, right) => (
    Math.abs(left.score - right.score) <= tolerance
      ? left.index - right.index
      : right.score - left.score
  ));
  unhealthy.sort((left, right) => right.score - left.score || left.index - right.index);
  return [...healthy, ...unhealthy].map(item => item.provider);
}
