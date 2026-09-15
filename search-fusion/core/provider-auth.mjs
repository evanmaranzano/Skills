import { loadJson } from "./load-config.mjs";
import { OAUTH_CLIENTS, loadStoredToken, tokenIsFresh } from "./oauth.mjs";

const AUTH_REGISTRY = "../config/provider-auth.json";

// Capabilities search() may hand to the adapter alongside the query.
export const PROVIDER_ENDPOINTS = {
  exa: { method: "POST", url: "https://api.exa.ai/search" },
  tavily: { method: "POST", url: "https://api.tavily.com/search" },
  brave: { method: "GET", url: "https://api.search.brave.com/res/v1/web/search" },
  firecrawl: { method: "POST", url: "https://api.firecrawl.dev/v1/search" },
  jina: { method: "GET", url: "https://s.jina.ai" },
  gemini: { method: "POST", url: "https://generativelanguage.googleapis.com/v1beta/models" },
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

// "gemini" search credentials can come from either Code Assist OAuth login;
// each stores under its own key in ~/.search-fusion/auth.json.
export const GEMINI_OAUTH_SOURCES = ["antigravity", "gemini-cli"];

export function oauthSupported(providerId) {
  if (providerId === "gemini") return true;
  return Boolean(OAUTH_CLIENTS[providerId]);
}

function oauthSourceFor(providerId, home) {
  if (providerId !== "gemini") return providerId;
  for (const source of GEMINI_OAUTH_SOURCES) {
    const token = loadStoredToken(source, home);
    if (token?.access_token) return source;
  }
  return null;
}

/** OAuth token state for a provider: valid / expired / absent. */
export function detectOauthState(providerId, home) {
  if (!oauthSupported(providerId)) return { supported: false, state: "unsupported" };
  const source = oauthSourceFor(providerId, home);
  if (!source) return { supported: true, state: "absent", email: undefined };
  const token = loadStoredToken(source, home);
  return {
    supported: true,
    state: tokenIsFresh(token) ? "valid" : "expired",
    email: token.email,
    source,
    projectId: token.projectId,
  };
}

/**
 * Per-provider credential status. Status resolution follows the same
 * preference as `--auth-mode auto`: env key first, then a stored OAuth token,
 * then keyless.
 */
export function detectProviderAuth(providerId, env = process.env, home = undefined) {
  const entries = authEntries(providerId);
  if (entries.length === 0) return { provider: providerId, status: "unknown", modes: [] };
  const modes = [];
  for (const entry of entries) {
    if (entry.type === "env") {
      const varName = envVarFor(entry, providerId);
      modes.push({ ...entry, var: varName, present: Boolean(env[varName]) });
    } else if (entry.type === "oauth") {
      const oauth = detectOauthState(providerId, home);
      modes.push({ ...entry, present: oauth.state === "valid" || oauth.state === "expired", oauthState: oauth.state, email: oauth.email });
    } else {
      modes.push({ ...entry, present: false });
    }
  }
  const readyEnv = modes.find(mode => mode.type === "env" && mode.present);
  if (readyEnv) return { provider: providerId, status: "ready", via: "env", mode: readyEnv, modes };
  const readyOauth = modes.find(mode => mode.type === "oauth" && mode.present);
  if (readyOauth) {
    return { provider: providerId, status: "ready", via: "oauth", mode: readyOauth, modes };
  }
  if (modes.some(mode => mode.type === "keyless")) return { provider: providerId, status: "keyless", via: "keyless", mode: modes.find(mode => mode.type === "keyless"), modes };
  return { provider: providerId, status: "missing", via: null, modes };
}

/** Providers the direct adapter can actually execute right now. */
export function readyDirectProviders(env = process.env, home = undefined) {
  const candidates = Object.keys(PROVIDER_ENDPOINTS);
  return candidates.filter(id => {
    const status = detectProviderAuth(id, env, home).status;
    return status === "ready" || status === "keyless";
  });
}

/**
 * Resolve the credential to use for one provider under a mode preference.
 * mode: "auto" (env key first, then stored OAuth token) | "key" | "oauth".
 * Returns { kind: "env-key" | "oauth" | "keyless" | null, value, var? }.
 */
export function resolveCredential(providerId, mode = "auto", env = process.env, home = undefined) {
  const detection = detectProviderAuth(providerId, env, home);
  const envMode = detection.modes?.find(entry => entry.type === "env");
  const envValue = envMode?.present ? env[envMode.var] : undefined;
  const oauthAvailable = oauthSupported(providerId) && detectOauthState(providerId, home).state !== "absent";

  if (mode === "key") {
    return envValue ? { kind: "env-key", value: envValue, var: envMode.var } : { kind: null };
  }
  if (mode === "oauth") {
    return oauthAvailable ? { kind: "oauth", value: null, source: detectOauthState(providerId, home).source } : { kind: null };
  }
  // auto
  if (envValue) return { kind: "env-key", value: envValue, var: envMode.var };
  if (oauthAvailable) return { kind: "oauth", value: null, source: detectOauthState(providerId, home).source };
  return { kind: detection.status === "keyless" ? "keyless" : null };
}

function tutorialLines(id, detection) {
  const lines = [];
  const label = registry()[id]?.label ?? id;
  if (detection.status === "ready") {
    const via = detection.via === "oauth"
      ? `oauth token${detection.mode.email ? ` (${detection.mode.email})` : ""}`
      : detection.mode.var;
    lines.push(`✅ ${label} (${id}): ready via ${via}`);
    return lines;
  }
  if (detection.status === "keyless") {
    lines.push(`🌐 ${label} (${id}): keyless, no configuration needed`);
    return lines;
  }
  lines.push(`❌ ${label} (${id}): not configured`);
  for (const mode of detection.modes) {
    if (mode.type === "env") {
      lines.push(`   key:  set ${mode.var}  # ${mode.signupUrl ?? ""}${mode.note ? ` — ${mode.note}` : ""}`);
      const shell = process.platform === "win32"
        ? `   PowerShell: [Environment]::SetEnvironmentVariable("${mode.var}", "<key>", "User")`
        : `   shell: export ${mode.var}="<key>"  # add to ~/.bashrc or ~/.zshrc`;
      lines.push(shell);
    } else if (mode.type === "oauth") {
      if (mode.oauthState === "expired") {
        lines.push(`   oauth: token expired — run \`--login ${id}\` again to refresh`);
      } else if (oauthSupported(id)) {
        if (id === "gemini") {
          lines.push(`   oauth: run \`--login antigravity\` or \`--login gemini-cli\` to pull a token (Cloud Code Assist; stored in ~/.search-fusion/auth.json)`);
        } else {
          lines.push(`   oauth: run \`--login ${id}\` to pull a token (stored in ~/.search-fusion/auth.json)`);
        }
      } else {
        lines.push(`   oauth: ${mode.guide}`);
      }
    }
  }
  return lines;
}

/**
 * Optional live probe: one minimal real request per ready provider to verify
 * the credential is still valid (a present-but-revoked key or expired OAuth
 * grant surfaces as invalid).
 */
export async function probeReadyProviders(env = process.env, options = {}) {
  const results = [];
  for (const id of readyDirectProviders(env, options.home)) {
    try {
      const { createDirectAdapter } = await import("../adapters/direct.mjs");
      const adapter = createDirectAdapter({ env, providers: [id], home: options.home });
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
export function renderDoctorReport(env = process.env, liveResults = null, home = undefined) {
  const ids = Object.keys(registry());
  const lines = ["search-fusion provider auth report", "=".repeat(36)];
  const directCapable = new Set(Object.keys(PROVIDER_ENDPOINTS));
  for (const id of ids) {
    lines.push(...tutorialLines(id, detectProviderAuth(id, env, home)));
  }
  const ready = readyDirectProviders(env, home);
  lines.push("");
  if (liveResults) {
    for (const probe of liveResults) {
      lines.push(probe.live
        ? `🔌 live probe ${probe.provider}: credential valid`
        : `🔌 live probe ${probe.provider}: FAILED — ${probe.error}`);
    }
    lines.push("");
  }
  lines.push(`--adapter direct will use: ${ready.length ? ready.join(", ") : "(nothing — set at least one env key; duckduckgo works without one)"}`);
  const orchestrationNote = ids.filter(id => !directCapable.has(id) && detectProviderAuth(id, env, home).status === "missing");
  if (orchestrationNote.length) {
    lines.push(`adapters/direct.mjs does not implement: ${orchestrationNote.join(", ")} (declare them via --capabilities for harness-mediated use)`);
  }
  return lines.join("\n");
}
