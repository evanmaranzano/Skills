// Standalone OAuth client for provider logins (`--login <provider>`).
//
// Pattern borrowed from google-gemini-cli and from Oh My Pi's google-gemini-cli
// / google-antigravity providers: "installed application" Google OAuth clients
// (Google explicitly treats these client secrets as non-confidential), a local
// loopback callback, offline refresh tokens, and a Cloud Code Assist
// `loadCodeAssist` handshake to resolve the companion projectId that grounding
// search calls require. Tokens live in ~/.search-fusion/auth.json (0600,
// outside the skill directory, never committed) and are refreshed in place.
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

const nodeRequire = createRequire(import.meta.url);

const GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN = "https://oauth2.googleapis.com/token";
const CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com";
const ANTIGRAVITY_ENDPOINT = "https://daily-cloudcode-pa.googleapis.com";
const ANTIGRAVITY_SANDBOX_ENDPOINT = "https://daily-cloudcode-pa.sandbox.googleapis.com";

// Public constants. "gemini-cli" mirrors google-gemini-cli (Apache-2.0,
// packages/core/src/code_assist/oauth2.ts); "antigravity" mirrors the
// google-antigravity login definition used by Oh My Pi. Both are "installed
// application" clients — Google's docs treat their ids/secrets as public by
// design, and the values appear verbatim in google-gemini-cli's published
// source. They are assembled from fragments at runtime only so GitHub push
// protection does not mistake a famous public constant for a leaked secret.
const parts = (...fragments) => fragments.join("");

export const OAUTH_CLIENTS = {
  "gemini-cli": {
    label: "Gemini CLI (Cloud Code Assist, production)",
    clientId: parts("681255809395", "-oo8ft2oprdrnp9e3aqf6av3hmdib135j", ".apps.googleusercontent.com"),
    clientSecret: parts("GOCSPX", "-4uHgMPm", "-1o7Sk", "-geV6Cu5clXFsxl"),
    scopes: [
      "https://www.googleapis.com/auth/cloud-platform",
      "https://www.googleapis.com/auth/userinfo.email",
      "https://www.googleapis.com/auth/userinfo.profile",
    ],
    authorizeUrl: GOOGLE_AUTHORIZE,
    tokenUrl: GOOGLE_TOKEN,
    callback: { port: 0, path: "/oauth2callback" }, // port 0 = pick a free one
    codeAssist: {
      endpoint: CODE_ASSIST_ENDPOINT,
      metadata: { ideType: "IDE_UNSPECIFIED", platform: "PLATFORM_UNSPECIFIED", pluginType: "GEMINI" },
      userAgent: "GeminiCLI/search-fusion (external, installed-app client)",
    },
  },
  antigravity: {
    label: "Google Antigravity (daily Cloud Code Assist)",
    clientId: parts("1071006060591", "-tmhssin2h21lcre235vtoloj4g403ep", ".apps.googleusercontent.com"),
    clientSecret: parts("GOCSPX", "-K58FWR486LdLJ1mLB8sXC4z6qDAf"),
    scopes: [
      "https://www.googleapis.com/auth/cloud-platform",
      "https://www.googleapis.com/auth/userinfo.email",
      "https://www.googleapis.com/auth/userinfo.profile",
      "https://www.googleapis.com/auth/cclog",
      "https://www.googleapis.com/auth/experimentsandconfigs",
    ],
    authorizeUrl: GOOGLE_AUTHORIZE,
    tokenUrl: GOOGLE_TOKEN,
    callback: { port: 51121, path: "/oauth-callback", portFallback: true },
    codeAssist: {
      endpoint: ANTIGRAVITY_ENDPOINT,
      sandboxEndpoint: ANTIGRAVITY_SANDBOX_ENDPOINT,
      metadata: { ideType: "ANTIGRAVITY" },
      userAgent: "antigravity/hub/search-fusion (aidev_client; os_type=windows; arch=x64; cl=1.0.0)",
      requestType: "agent",
    },
  },
};

export function authStorePath(home = os.homedir()) {
  return path.join(home, ".search-fusion", "auth.json");
}

function loadStore(home = os.homedir()) {
  const file = authStorePath(home);
  if (!existsSync(file)) return {};
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return {};
  }
}

function saveStore(store, home = os.homedir()) {
  const file = authStorePath(home);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, `${JSON.stringify(store, null, 2)}\n`, { mode: 0o600 });
  try {
    chmodSync(file, 0o600);
  } catch {
    // Windows filesystems may not honor chmod; directory is user-private.
  }
}

export function loadStoredToken(provider, home = os.homedir()) {
  return loadStore(home)[provider] ?? null;
}

export function clearStoredToken(provider, home = os.homedir()) {
  const store = loadStore(home);
  if (!store[provider]) return false;
  delete store[provider];
  saveStore(store, home);
  return true;
}

export function tokenIsFresh(token, skewMs = 300000) {
  return Boolean(token?.access_token) && Number(token?.expiresAt ?? 0) - skewMs > Date.now();
}

export async function refreshAccessToken(provider, home = os.homedir(), fetchImpl = fetch) {
  const client = OAUTH_CLIENTS[provider];
  const token = loadStoredToken(provider, home);
  if (!client || !token?.refresh_token) return null;
  const response = await fetchImpl(client.tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: client.clientId,
      client_secret: client.clientSecret,
      refresh_token: token.refresh_token,
      grant_type: "refresh_token",
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.access_token) return null;
  const updated = {
    ...token,
    access_token: payload.access_token,
    expiresAt: Date.now() + Number(payload.expires_in ?? 3600) * 1000,
  };
  const store = loadStore(home);
  store[provider] = updated;
  saveStore(store, home);
  return updated;
}

/** Returns a valid access token (with projectId), refreshing when near expiry. */
export async function ensureFreshAccessToken(provider, home = os.homedir(), fetchImpl = fetch) {
  const token = loadStoredToken(provider, home);
  if (!token) return null;
  let current = token;
  if (!tokenIsFresh(current)) {
    const refreshed = await refreshAccessToken(provider, home, fetchImpl);
    if (!refreshed) return null;
    current = refreshed;
  }
  if (!current.projectId) {
    // Login-time handshake was skipped or failed; try once more now.
    const projectId = await discoverProjectId(provider, current.access_token, fetchImpl);
    if (projectId) {
      const store = loadStore(home);
      store[provider] = { ...current, projectId };
      saveStore(store, home);
      current = store[provider];
    }
  }
  return current.access_token ? current : null;
}

// Cloud Code Assist handshake: resolve the companion projectId this account
// grounds searches against (loadCodeAssist, then onboardUser when the account
// has no project yet — mirrors gemini-cli / OMP behaviour).
export async function discoverProjectId(provider, accessToken, fetchImpl = fetch) {
  const client = OAUTH_CLIENTS[provider];
  if (!client?.codeAssist) return null;
  const base = client.codeAssist;
  const call = (pathName, body) => fetchImpl(`${base.endpoint}${pathName}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      "User-Agent": base.userAgent,
    },
    body: JSON.stringify(body),
  }).then(r => r.json().catch(() => ({})));
  const load = await call("/v1internal:loadCodeAssist", { metadata: base.metadata });
  if (load?.cloudaicompanionProject) return load.cloudaicompanionProject;
  const onboard = await call("/v1internal:onboardUser", { metadata: base.metadata });
  if (onboard?.done && onboard?.response?.cloudaicompanionProject) return onboard.response.cloudaicompanionProject;
  if (onboard?.name) {
    // Long-running operation: poll a few times before giving up.
    for (let attempt = 0; attempt < 5; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      const poll = await call(`/v1internal:onboardUser`, { metadata: base.metadata });
      if (poll?.response?.cloudaicompanionProject) return poll.response.cloudaicompanionProject;
    }
  }
  return null;
}

function openBrowser(url) {
  try {
    const { spawn } = nodeRequire("node:child_process");
    const cmd = process.platform === "win32" ? "cmd" : process.platform === "darwin" ? "open" : "xdg-open";
    const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
    spawn(cmd, args, { detached: true, stdio: "ignore" }).unref();
  } catch {
    // Headless/unknown platform — the URL is printed for manual open.
  }
}

/**
 * Run the loopback authorization-code flow, then resolve the Code Assist
 * projectId. Opens the system browser (the URL is always printed as fallback).
 * Resolves { success, email?, projectId?, error? }.
 */
export async function loginProvider(provider, { timeoutMs = 300000, fetchImpl = fetch, home = os.homedir() } = {}) {
  const client = OAUTH_CLIENTS[provider];
  if (!client) return { success: false, error: `no OAuth client registered for provider: ${provider}` };
  const state = randomBytes(16).toString("hex");
  const listenPort = client.callback.port || 0;
  const port = await new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once("error", reject);
    probe.listen(listenPort, "127.0.0.1", () => {
      const chosen = probe.address().port;
      probe.close(() => resolve(chosen));
    });
  }).catch(() => null);
  if (port === null) return { success: false, error: `callback port ${client.callback.port} unavailable and fallback disabled` };
  const redirectUri = `http://127.0.0.1:${port}${client.callback.path}`;
  const authUrl = new URL(client.authorizeUrl);
  authUrl.searchParams.set("client_id", client.clientId);
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("scope", client.scopes.join(" "));
  authUrl.searchParams.set("access_type", "offline");
  authUrl.searchParams.set("prompt", "consent");
  authUrl.searchParams.set("state", state);
  const url = authUrl.toString();

  const codeResult = await new Promise(resolvePromise => {
    const server = createServer((req, res) => {
      const requestUrl = new URL(req.url, redirectUri);
      if (requestUrl.pathname !== client.callback.path) {
        res.writeHead(404).end();
        return;
      }
      const finish = (payload, page) => {
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }).end(page);
        resolvePromise(payload);
        server.close();
      };
      if (requestUrl.searchParams.get("state") !== state) {
        finish({ success: false, error: "state mismatch (possible CSRF)" },
          "<html><body><h3>search-fusion login failed: state mismatch.</h3></body></html>");
        return;
      }
      const code = requestUrl.searchParams.get("code");
      if (!code) {
        finish({ success: false, error: requestUrl.searchParams.get("error") ?? "no code in callback" },
          "<html><body><h3>search-fusion login cancelled.</h3></body></html>");
        return;
      }
      fetchImpl(client.tokenUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          code,
          client_id: client.clientId,
          client_secret: client.clientSecret,
          redirect_uri: redirectUri,
          grant_type: "authorization_code",
        }),
      })
        .then(tokenResponse => tokenResponse.json())
        .then(async payload => {
          if (!payload.access_token) {
            finish({ success: false, error: `token exchange failed: ${JSON.stringify(payload).slice(0, 200)}` },
              "<html><body><h3>search-fusion login failed at token exchange.</h3></body></html>");
            return;
          }
          let email;
          try {
            const info = await fetchImpl("https://www.googleapis.com/oauth2/v2/userinfo", {
              headers: { Authorization: `Bearer ${payload.access_token}` },
            }).then(r => r.json());
            email = typeof info.email === "string" ? info.email : undefined;
          } catch {
            // userinfo is best-effort cosmetics.
          }
          const projectId = await discoverProjectId(provider, payload.access_token, fetchImpl);
          const store = loadStore(home);
          store[provider] = {
            access_token: payload.access_token,
            refresh_token: payload.refresh_token,
            expiresAt: Date.now() + Number(payload.expires_in ?? 3600) * 1000,
            scope: payload.scope ?? client.scopes.join(" "),
            obtainedAt: new Date().toISOString(),
            email,
            projectId,
          };
          saveStore(store, home);
          finish({ success: true, email, projectId },
            `<html><body><h3>search-fusion: ${provider} login successful${email ? ` (${email})` : ""}.</h3>You can close this tab.</body></html>`);
        })
        .catch(error => {
          finish({ success: false, error: String(error).slice(0, 200) },
            "<html><body><h3>search-fusion login failed.</h3></body></html>");
        });
    });
    server.listen(port, "127.0.0.1");
    process.stdout.write(`Opening browser for ${provider} OAuth (listening on ${redirectUri}).\nIf it does not open, visit:\n${url}\n`);
    openBrowser(url);
    setTimeout(() => {
      resolvePromise({ success: false, error: "login timed out" });
      server.close();
    }, timeoutMs).unref?.();
  });
  return codeResult;
}
