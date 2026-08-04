/**
 * Minimal OIDC Authorization Code + PKCE client for the browser.
 *
 * Access tokens live in module memory only. sessionStorage holds only the
 * transient login handshake (state, nonce, verifier, return path) between the
 * redirect to the identity provider and the callback, and is cleared on use.
 * Nothing here is ever logged.
 */

import { challengeS256, generateVerifier, randomToken } from "./pkce";

export interface AuthConfiguration {
  oidc_enabled: boolean;
  issuer_url: string | null;
  client_id: string | null;
  audience: string | null;
  redirect_uri: string | null;
  scopes: string;
  developer_identity_enabled: boolean;
}

export class AuthError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

interface Discovery {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
}

interface Handshake {
  state: string;
  nonce: string;
  verifier: string;
  returnTo: string;
}

interface StoredTokens {
  accessToken: string;
  expiresAt: number | null;
}

const HANDSHAKE_KEY = "fusion-helpdesk-oidc-handshake";

let tokens: StoredTokens | null = null;

export function getAccessToken(): string | null {
  if (!tokens) return null;
  if (tokens.expiresAt !== null && Date.now() >= tokens.expiresAt) {
    tokens = null;
    return null;
  }
  return tokens.accessToken;
}

export function clearTokens(): void {
  tokens = null;
  sessionStorage.removeItem(HANDSHAKE_KEY);
}

export function __resetAuthForTests(): void {
  clearTokens();
}

export function sanitizeReturnTo(raw: string | null | undefined): string {
  if (!raw) return "/";
  if (!raw.startsWith("/")) return "/";
  if (raw.startsWith("//") || raw.startsWith("/\\")) return "/";
  return raw;
}

export async function fetchAuthConfiguration(
  baseUrl: string,
): Promise<AuthConfiguration> {
  const response = await fetch(`${baseUrl}/api/v1/auth/configuration`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new AuthError(
      "configuration_unavailable",
      "The sign-in configuration could not be loaded.",
    );
  return (await response.json()) as AuthConfiguration;
}

async function discover(issuer: string): Promise<Discovery> {
  const response = await fetch(
    `${issuer.replace(/\/$/, "")}/.well-known/openid-configuration`,
    { headers: { Accept: "application/json" } },
  );
  if (!response.ok)
    throw new AuthError(
      "discovery_failed",
      "The identity provider could not be reached.",
    );
  const payload = (await response.json()) as Partial<Discovery>;
  if (
    !payload.authorization_endpoint ||
    !payload.token_endpoint ||
    payload.issuer !== issuer
  )
    throw new AuthError(
      "discovery_invalid",
      "The identity provider returned an invalid configuration.",
    );
  return payload as Discovery;
}

function requireOidcValues(configuration: AuthConfiguration): {
  issuer: string;
  clientId: string;
  redirectUri: string;
} {
  if (
    !configuration.oidc_enabled ||
    !configuration.issuer_url ||
    !configuration.client_id ||
    !configuration.redirect_uri
  )
    throw new AuthError(
      "oidc_not_configured",
      "Single sign-on is not configured.",
    );
  return {
    issuer: configuration.issuer_url,
    clientId: configuration.client_id,
    redirectUri: configuration.redirect_uri,
  };
}

export async function beginLogin(
  configuration: AuthConfiguration,
  returnTo: string,
): Promise<void> {
  const { issuer, clientId, redirectUri } = requireOidcValues(configuration);
  const discovery = await discover(issuer);
  const handshake: Handshake = {
    state: randomToken(),
    nonce: randomToken(),
    verifier: generateVerifier(),
    returnTo: sanitizeReturnTo(returnTo),
  };
  sessionStorage.setItem(HANDSHAKE_KEY, JSON.stringify(handshake));
  const target = new URL(discovery.authorization_endpoint);
  target.searchParams.set("response_type", "code");
  target.searchParams.set("client_id", clientId);
  target.searchParams.set("redirect_uri", redirectUri);
  target.searchParams.set("scope", configuration.scopes);
  target.searchParams.set("state", handshake.state);
  target.searchParams.set("nonce", handshake.nonce);
  target.searchParams.set(
    "code_challenge",
    await challengeS256(handshake.verifier),
  );
  target.searchParams.set("code_challenge_method", "S256");
  if (configuration.audience)
    target.searchParams.set("audience", configuration.audience);
  location.assign(target.toString());
}

function decodeJwtPayload(token: string): Record<string, unknown> {
  const segment = token.split(".")[1] ?? "";
  const normalized = segment.replaceAll("-", "+").replaceAll("_", "/");
  const padded = normalized.padEnd(
    normalized.length + ((4 - (normalized.length % 4)) % 4),
    "=",
  );
  try {
    return JSON.parse(atob(padded)) as Record<string, unknown>;
  } catch {
    throw new AuthError("invalid_id_token", "The sign-in response is invalid.");
  }
}

function validateIdToken(
  idToken: string,
  issuer: string,
  clientId: string,
  nonce: string,
): void {
  const claims = decodeJwtPayload(idToken);
  const audience = claims.aud;
  const audienceMatches = Array.isArray(audience)
    ? audience.includes(clientId)
    : audience === clientId;
  const expiry = typeof claims.exp === "number" ? claims.exp : 0;
  if (
    claims.iss !== issuer ||
    !audienceMatches ||
    claims.nonce !== nonce ||
    expiry * 1000 <= Date.now()
  )
    throw new AuthError("invalid_id_token", "The sign-in response is invalid.");
}

export async function completeLogin(
  configuration: AuthConfiguration,
  params: URLSearchParams,
): Promise<{ returnTo: string }> {
  const { issuer, clientId, redirectUri } = requireOidcValues(configuration);
  const stored = sessionStorage.getItem(HANDSHAKE_KEY);
  sessionStorage.removeItem(HANDSHAKE_KEY);
  if (!stored)
    throw new AuthError(
      "missing_handshake",
      "The sign-in attempt has expired. Start again.",
    );
  const handshake = JSON.parse(stored) as Handshake;
  const providerError = params.get("error");
  if (providerError)
    throw new AuthError(
      providerError,
      "The identity provider rejected sign-in.",
    );
  if (!params.get("code") || params.get("state") !== handshake.state)
    throw new AuthError(
      "state_mismatch",
      "The sign-in response failed the state check.",
    );
  const discovery = await discover(issuer);
  const response = await fetch(discovery.token_endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: params.get("code") ?? "",
      redirect_uri: redirectUri,
      client_id: clientId,
      code_verifier: handshake.verifier,
    }).toString(),
  });
  if (!response.ok)
    throw new AuthError("token_exchange_failed", "Sign-in could not complete.");
  const payload = (await response.json()) as {
    access_token?: string;
    id_token?: string;
    expires_in?: number;
  };
  if (!payload.access_token)
    throw new AuthError("token_exchange_failed", "Sign-in could not complete.");
  if (payload.id_token)
    validateIdToken(payload.id_token, issuer, clientId, handshake.nonce);
  tokens = {
    accessToken: payload.access_token,
    expiresAt:
      typeof payload.expires_in === "number"
        ? Date.now() + payload.expires_in * 1000
        : null,
  };
  return { returnTo: sanitizeReturnTo(handshake.returnTo) };
}
