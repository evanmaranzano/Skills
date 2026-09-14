import { loadJson } from "./load-config.mjs";

const AUTH_REGISTRY = "../config/provider-auth.json";

// Capabilities search() may hand to the adapter alongside the query.
export const PROVIDER_ENDPOINTS = {
  exa: { method: "POST", url: "https://api.exa.ai/search" },
  tavily: { method: "POST", url: "https://api.tavily.com/search" },
  brave: { method: "GET", url: "https://api.search.brave.com/res/v1/web/search" },
  firecrawl: { method: "POST", url: "https://api.firecrawl.dev/v1/search" },
  jina: { method: "GET", url: "https://s.jina.ai" },
  duckduckgo: { method: "POST", url: "https://html.duckduckgo.com/html/" },
};

function registry() {
  return loadJson(AUTH_REGISTRY, import.meta.url).providers;
}

export function knownAuthProviders() {
  return Object.keys(registry());
}

function envVarFor(entry, providerId) {
  if (entry.type !== "env") return undefined;
  if (entry.var) return entry.var;
  return `${providerId.toUpperCase()}_API_KEY`;
}

export function authEntries(providerId) {
  return registry()[providerId]?.auth ?? [];
}

/** Per-provider credential status: ready (env key set) / keyless / missing. */
export function detectProviderAuth(providerId, env = process.env) {
  const entries = authEntries(providerId);
  if (entries.length === 0) return { provider: providerId, status: "unknown", modes: [] };
  const modes = [];
  for (const entry of entries) {
    if (entry.type === "env") {
      const varName = envVarFor(entry, providerId);
      const present = Boolean(env[varName]);
      modes.push({ ...entry, var: varName, present });
    } else {
      modes.push({ ...entry, present: false });
    }
  }
  const readyEnv = modes.find(mode => mode.type === "env" && mode.present);
  if (readyEnv) return { provider: providerId, status: "ready", mode: readyEnv, modes };
  if (modes.some(mode => mode.type === "keyless")) return { provider: providerId, status: "keyless", mode: modes.find(mode => mode.type === "keyless"), modes };
  return { provider: providerId, status: "missing", modes };
}

/** Providers the direct adapter can actually execute right now. */
export function readyDirectProviders(env = process.env) {
  const candidates = Object.keys(PROVIDER_ENDPOINTS);
  const ready = candidates.filter(id => {
    const status = detectProviderAuth(id, env).status;
    return status === "ready" || status === "keyless";
  });
  return ready;
}

function tutorialLines(id, detection) {
  const lines = [];
  const label = registry()[id]?.label ?? id;
  if (detection.status === "ready") {
    lines.push(`✅ ${label} (${id}): ready via ${detection.mode.var}`);
    return lines;
  }
  if (detection.status === "keyless") {
    lines.push(`🌐 ${label} (${id}): keyless, no configuration needed`);
    return lines;
  }
  lines.push(`❌ ${label} (${id}): not configured`);
  for (const mode of detection.modes) {
    if (mode.type === "env") {
      lines.push(`   set ${mode.var}  # ${mode.signupUrl ?? ""}${mode.note ? ` — ${mode.note}` : ""}`);
      const shell = process.platform === "win32"
        ? `   PowerShell: [Environment]::SetEnvironmentVariable("${mode.var}", "<key>", "User")`
        : `   shell: export ${mode.var}="<key>"  # add to ~/.bashrc or ~/.zshrc`;
      lines.push(shell);
    } else if (mode.type === "oauth") {
      lines.push(`   oauth: ${mode.guide}`);
    }
  }
  return lines;
}

/**
 * Optional live probe: one minimal real request per ready provider to verify
 * the key is still valid (a present-but-revoked key surfaces as invalid).
 */
export async function probeReadyProviders(env = process.env) {
  const results = [];
  for (const id of readyDirectProviders(env)) {
    const detection = detectProviderAuth(id, env);
    if (detection.status !== "ready") continue;
    try {
      const { createDirectAdapter } = await import("../adapters/direct.mjs");
      const adapter = createDirectAdapter({ env, providers: [id] });
      await adapter.search({ provider: id, query: "search fusion probe", limit: 1 });
      results.push({ provider: id, live: true });
    } catch (error) {
      results.push({ provider: id, live: false, error: String(error.message ?? error).slice(0, 160) });
    }
  }
  return results;
}

/**
 * First-run onboarding report: per-provider credential status + exact setup
 * instructions. Rendered by `--doctor`; contains no secret values.
 */
export function renderDoctorReport(env = process.env, liveResults = null) {
  const ids = Object.keys(registry());
  const lines = ["search-fusion provider auth report", "=".repeat(36)];
  const directCapable = new Set(Object.keys(PROVIDER_ENDPOINTS));
  for (const id of ids) {
    lines.push(...tutorialLines(id, detectProviderAuth(id, env)));
  }
  const ready = readyDirectProviders(env);
  lines.push("");
  if (liveResults) {
    for (const probe of liveResults) {
      lines.push(probe.live
        ? `🔌 live probe ${probe.provider}: key valid`
        : `🔌 live probe ${probe.provider}: FAILED — ${probe.error}`);
    }
    lines.push("");
  }
  lines.push(`--adapter direct will use: ${ready.length ? ready.join(", ") : "(nothing — set at least one env key; duckduckgo works without one)"}`);
  const orchestrationNote = ids.filter(id => !directCapable.has(id) && detectProviderAuth(id, env).status === "missing");
  if (orchestrationNote.length) {
    lines.push(`adapters/direct.mjs does not implement: ${orchestrationNote.join(", ")} (declare them via --capabilities for harness-mediated use)`);
  }
  return lines.join("\n");
}
