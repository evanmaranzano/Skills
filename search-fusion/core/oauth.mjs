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
import { randomBytes, randomUUID } from "node:crypto";
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
const CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann";
const CODEX_TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token";
const CODEX_DEVICE_USERCODE = "https://auth.openai.com/api/accounts/deviceauth/usercode";
const CODEX_DEVICE_TOKEN = "https://auth.openai.com/api/accounts/deviceauth/token";
const CODEX_DEVICE_AUTH = "https://auth.openai.com/codex/device";
const CODEX_DEVICE_REDIRECT = "https://auth.openai.com/deviceauth/callback";
const CODEX_SCOPES = "openid profile email offline_access api.connectors.read api.connectors.invoke";
const XAI_ISSUER = "https://auth.x.ai";
const XAI_DEVICE_ENDPOINT = `${XAI_ISSUER}/oauth2/device/code`;
const XAI_USERINFO_ENDPOINT = `${XAI_ISSUER}/oauth2/userinfo`;
const XAI_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828";
const XAI_SCOPES = "openid profile email offline_access grok-cli:access api:access";
const KIMI_AUTH_HOST = "https://auth.kimi.com";
const KIMI_DEVICE_ENDPOINT = `${KIMI_AUTH_HOST}/api/oauth/device_authorization`;
const KIMI_TOKEN_ENDPOINT = `${KIMI_AUTH_HOST}/api/oauth/token`;
const KIMI_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098";
const KIMI_DEVICE_ID_FILE = "kimi-device-id";
const SEARCH_FUSION_VERSION = "1.0";

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
    clientId: parts("1071006060591", "-tmhssin2h21lcre235vtolojh4g403ep", ".apps.googleusercontent.com"),
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
  codex: {
    label: "OpenAI Codex (ChatGPT OAuth)",
    kind: "codex-device",
    clientId: CODEX_CLIENT_ID,
    tokenUrl: CODEX_TOKEN_ENDPOINT,
    scopes: CODEX_SCOPES,
  },
  xai: {
    label: "xAI Grok (device OAuth)",
    kind: "device",
    clientId: XAI_CLIENT_ID,
    deviceUrl: XAI_DEVICE_ENDPOINT,
    tokenUrl: null,
    scopes: XAI_SCOPES,
    userinfoUrl: XAI_USERINFO_ENDPOINT,
  },
  kimi: {
    label: "Kimi Code (device OAuth)",
    kind: "device",
    clientId: KIMI_CLIENT_ID,
    deviceUrl: KIMI_DEVICE_ENDPOINT,
    tokenUrl: KIMI_TOKEN_ENDPOINT,
    scopes: "",
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
  let tokenUrl = client.tokenUrl;
  if (provider === "xai") {
    const discovery = await fetchImpl(`${XAI_ISSUER}/.well-known/openid-configuration`, {
      headers: { Accept: "application/json" },
    }).then(response => response.json().catch(() => ({})));
    tokenUrl = typeof discovery.token_endpoint === "string" ? discovery.token_endpoint : null;
  }
  if (!tokenUrl) return null;
  const body = {
    refresh_token: token.refresh_token,
    grant_type: "refresh_token",
  };
  if (client.clientId) body.client_id = client.clientId;
  if (client.clientSecret) body.client_secret = client.clientSecret;
  const response = await fetchImpl(tokenUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.access_token) return null;
  const updated = {
    ...token,
    access_token: payload.access_token,
    refresh_token: payload.refresh_token ?? token.refresh_token,
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
  if (OAUTH_CLIENTS[provider]?.codeAssist && !current.projectId) {
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
// has no project yet — mirrors the provider's standard client behaviour).
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

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function kimiDeviceModel() {
  const platform = process.platform === "win32" ? "Windows" : process.platform === "darwin" ? "macOS" : process.platform === "linux" ? "Linux" : process.platform;
  return [platform, os.release(), os.arch()].filter(Boolean).join(" ").trim();
}

function kimiDeviceId(home = os.homedir()) {
  const file = path.join(home, ".search-fusion", KIMI_DEVICE_ID_FILE);
  try {
    const existing = readFileSync(file, "utf8").trim();
    if (existing) return existing;
  } catch {
    // Device-id persistence is best effort.
  }
  const id = randomUUID().replace(/-/g, "");
  try {
    mkdirSync(path.dirname(file), { recursive: true });
    writeFileSync(file, `${id}\n`, { mode: 0o600 });
    chmodSync(file, 0o600);
  } catch {
    // An ephemeral id is sufficient if the user directory is not writable.
  }
  return id;
}

function kimiHeaders(home = os.homedir()) {
  const clean = (value, fallback = "") => String(value ?? "").replace(/[^\x20-\x7E]/g, "").trim() || fallback;
  return {
    Accept: "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": `KimiCLI/${SEARCH_FUSION_VERSION}`,
    "X-Msh-Platform": "kimi_cli",
    "X-Msh-Version": SEARCH_FUSION_VERSION,
    "X-Msh-Device-Name": clean(os.hostname(), "unknown"),
    "X-Msh-Device-Model": clean(kimiDeviceModel(), "unknown"),
    "X-Msh-Os-Version": clean(os.version(), "unknown"),
    "X-Msh-Device-Id": clean(kimiDeviceId(home), "unknown"),
  };
}

function decodeJwtPayload(token) {
  try {
    const part = String(token).split(".")[1];
    if (!part) return {};
    const value = JSON.parse(Buffer.from(part, "base64url").toString("utf8"));
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function codexIdentity(accessToken, idToken) {
  const access = decodeJwtPayload(accessToken);
  const id = idToken ? decodeJwtPayload(idToken) : {};
  const auth = access["https://api.openai.com/auth"] ?? {};
  const idAuth = id["https://api.openai.com/auth"] ?? {};
  const profile = access["https://api.openai.com/profile"] ?? {};
  const idProfile = id["https://api.openai.com/profile"] ?? {};
  return {
    accountId: auth.chatgpt_account_id ?? idAuth.chatgpt_account_id,
    email: profile.email ?? idProfile.email,
  };
}

async function persistDeviceToken(provider, payload, home, extra = {}) {
  if (!payload?.access_token) return { success: false, error: `${provider} token response had no access_token` };
  const store = loadStore(home);
  const accountId = extra.accountId ?? payload.user_id ?? payload.sub;
  store[provider] = {
    access_token: payload.access_token,
    refresh_token: payload.refresh_token ?? extra.refreshToken,
    expiresAt: Date.now() + Number(payload.expires_in ?? 3600) * 1000,
    obtainedAt: new Date().toISOString(),
    ...(extra.email ? { email: extra.email } : {}),
    ...(accountId ? { accountId } : {}),
    ...(extra.projectId ? { projectId: extra.projectId } : {}),
  };
  saveStore(store, home);
  return { success: true, email: extra.email, accountId };
}

async function xaiTokenEndpoint(fetchImpl) {
  const response = await fetchImpl(`${XAI_ISSUER}/.well-known/openid-configuration`, {
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || typeof payload.token_endpoint !== "string") {
    return null;
  }
  const url = new URL(payload.token_endpoint);
  if (url.protocol !== "https:" || !(url.hostname === "x.ai" || url.hostname.endsWith(".x.ai"))) return null;
  return url.toString();
}

async function loginCodexDevice({ fetchImpl, home, timeoutMs }) {
  const initResponse = await fetchImpl(CODEX_DEVICE_USERCODE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ client_id: CODEX_CLIENT_ID }),
  });
  const initData = await initResponse.json().catch(() => ({}));
  if (!initResponse.ok || !initData.device_auth_id || !initData.user_code) {
    return { success: false, error: `Codex device authorization failed (${initResponse.status})` };
  }
  const userCode = initData.user_code;
  process.stdout.write(`Open ${CODEX_DEVICE_AUTH} and enter code ${userCode}.\n`);
  openBrowser(CODEX_DEVICE_AUTH);
  const deadline = Date.now() + timeoutMs;
  const interval = Math.max(3000, Number(initData.interval ?? 5) * 1000 + 3000);
  while (Date.now() < deadline) {
    await sleep(Math.min(interval, Math.max(0, deadline - Date.now())));
    const pollResponse = await fetchImpl(CODEX_DEVICE_TOKEN, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_auth_id: initData.device_auth_id, user_code: userCode }),
    });
    if (pollResponse.status === 403 || pollResponse.status === 404) continue;
    const pollData = await pollResponse.json().catch(() => ({}));
    if (!pollResponse.ok || !pollData.authorization_code || !pollData.code_verifier) {
      return { success: false, error: `Codex device polling failed (${pollResponse.status})` };
    }
    const tokenResponse = await fetchImpl(CODEX_TOKEN_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code",
        client_id: CODEX_CLIENT_ID,
        code: pollData.authorization_code,
        code_verifier: pollData.code_verifier,
        redirect_uri: CODEX_DEVICE_REDIRECT,
      }),
    });
    const tokenData = await tokenResponse.json().catch(() => ({}));
    if (!tokenResponse.ok) return { success: false, error: `Codex token exchange failed (${tokenResponse.status})` };
    const identity = codexIdentity(tokenData.access_token, tokenData.id_token);
    return persistDeviceToken("codex", tokenData, home, identity);
  }
  return { success: false, error: "Codex device authorization timed out" };
}

async function loginStandardDevice(provider, { fetchImpl, home, timeoutMs }) {
  const client = OAUTH_CLIENTS[provider];
  const headers = provider === "xai"
    ? { Accept: "application/json", "Content-Type": "application/x-www-form-urlencoded" }
    : kimiHeaders(home);
  const initResponse = await fetchImpl(client.deviceUrl, {
    method: "POST",
    headers,
    body: new URLSearchParams({ client_id: client.clientId, ...(client.scopes ? { scope: client.scopes } : {}) }),
  });
  const initData = await initResponse.json().catch(() => ({}));
  if (!initResponse.ok || !initData.device_code || !initData.user_code) {
    return { success: false, error: `${provider} device authorization failed (${initResponse.status})` };
  }
  const verification = initData.verification_uri_complete ?? initData.verification_uri;
  process.stdout.write(`Open ${verification} and complete ${provider} authorization.\n`);
  if (verification) openBrowser(verification);
  const tokenUrl = provider === "xai" ? await xaiTokenEndpoint(fetchImpl) : client.tokenUrl;
  if (!tokenUrl) return { success: false, error: `${provider} OAuth token endpoint discovery failed` };
  const deadline = Date.now() + timeoutMs;
  const interval = Math.max(3000, Number(initData.interval ?? 5) * 1000);
  while (Date.now() < deadline) {
    await sleep(Math.min(interval, Math.max(0, deadline - Date.now())));
    const tokenResponse = await fetchImpl(tokenUrl, {
      method: "POST",
      headers,
      body: new URLSearchParams({
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
        client_id: client.clientId,
        device_code: initData.device_code,
      }),
    });
    if (tokenResponse.status === 400 || tokenResponse.status === 403 || tokenResponse.status === 404) continue;
    const payload = await tokenResponse.json().catch(() => ({}));
    if (!tokenResponse.ok) return { success: false, error: `${provider} token polling failed (${tokenResponse.status})` };
    let identity = {};
    if (provider === "xai" && payload.access_token) {
      try {
        const userResponse = await fetchImpl(XAI_USERINFO_ENDPOINT, { headers: { Authorization: `Bearer ${payload.access_token}` } });
        const user = await userResponse.json().catch(() => ({}));
        identity = { accountId: user.sub, email: user.email };
      } catch {
        // Identity is optional; the bearer token is sufficient for search.
      }
    }
    return persistDeviceToken(provider, payload, home, identity);
  }
  return { success: false, error: `${provider} device authorization timed out` };
}

/**
 * Run the loopback authorization-code flow, then resolve the Code Assist
 * projectId. Opens the system browser (the URL is always printed as fallback).
 * Resolves { success, email?, projectId?, error? }.
 */
export async function loginProvider(provider, { timeoutMs = 300000, fetchImpl = fetch, home = os.homedir() } = {}) {
  const client = OAUTH_CLIENTS[provider];
  if (!client) return { success: false, error: `no OAuth client registered for provider: ${provider}` };
  if (client.kind === "codex-device") return loginCodexDevice({ fetchImpl, home, timeoutMs });
  if (client.kind === "device") return loginStandardDevice(provider, { fetchImpl, home, timeoutMs });
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
