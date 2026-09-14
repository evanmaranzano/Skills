const DEFAULT_TIMEOUTS_BY_DEPTH = { quick: 90_000, verify: 150_000, deep: 180_000 };

export function normalizeSearchBudget(task = {}, options = {}) {
  const depth = task.depth ?? "verify";
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUTS_BY_DEPTH[depth] ?? DEFAULT_TIMEOUTS_BY_DEPTH.verify;
  const maxInitialProviders = Math.max(1, Math.min(options.providerCount ?? 3, 4));
  const maxSearchCalls = Math.max(1, Math.min(options.maxSearchCalls ?? 9, 12));
  const maxFallbackCalls = Math.max(0, Math.min(options.maxFallbackCalls ?? 2, 4));
  return {
    wallClockMs: timeoutMs,
    perCallTimeoutMs: Math.max(5_000, Math.min(options.perCallTimeoutMs ?? 45_000, timeoutMs)),
    maxInitialProviders,
    maxProviders: maxInitialProviders + maxFallbackCalls,
    maxSubqueries: Math.max(1, Math.min(options.maxSubqueries ?? 3, 4)),
    maxSearchCalls,
    maxFallbackCalls,
    maxFetches: Math.max(0, Math.min(options.maxFetches ?? 0, 12)),
  };
}
