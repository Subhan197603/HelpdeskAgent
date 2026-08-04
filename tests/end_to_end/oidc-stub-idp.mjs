// Test-only OIDC identity provider for Playwright end-to-end sign-in.
// Implements discovery, JWKS, authorization-code issuance with PKCE (S256)
// verification, and RS256 token minting. Never use outside local testing.
import {
  createHash,
  createSign,
  generateKeyPairSync,
  randomUUID,
} from "node:crypto";
import { createServer } from "node:http";

const PORT = 59180;
const ISSUER = `http://127.0.0.1:${PORT}`;
const AUDIENCE = "helpdesk-e2e-api";
const ALLOWED_REDIRECT = "http://127.0.0.1:53001/auth/callback";
const SUBJECT = "oidc-agent";
const KID = "e2e-signing-key";

const { publicKey, privateKey } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
});
const jwk = {
  ...publicKey.export({ format: "jwk" }),
  kid: KID,
  alg: "RS256",
  use: "sig",
};
const codes = new Map();

function base64Url(buffer) {
  return Buffer.from(buffer)
    .toString("base64")
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

function signJwt(payload) {
  const header = base64Url(
    JSON.stringify({ alg: "RS256", typ: "JWT", kid: KID }),
  );
  const body = base64Url(JSON.stringify(payload));
  const signer = createSign("RSA-SHA256");
  signer.update(`${header}.${body}`);
  return `${header}.${body}.${base64Url(signer.sign(privateKey))}`;
}

const corsHeaders = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, accept",
};

function json(response, status, payload) {
  response.writeHead(status, {
    "content-type": "application/json",
    ...corsHeaders,
  });
  response.end(JSON.stringify(payload));
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", ISSUER);
  if (request.method === "OPTIONS") {
    response.writeHead(204, corsHeaders);
    response.end();
    return;
  }
  if (url.pathname === "/.well-known/openid-configuration") {
    json(response, 200, {
      issuer: ISSUER,
      authorization_endpoint: `${ISSUER}/authorize`,
      token_endpoint: `${ISSUER}/token`,
      jwks_uri: `${ISSUER}/jwks`,
      response_types_supported: ["code"],
      code_challenge_methods_supported: ["S256"],
    });
    return;
  }
  if (url.pathname === "/jwks") {
    json(response, 200, { keys: [jwk] });
    return;
  }
  if (url.pathname === "/authorize") {
    const redirectUri = url.searchParams.get("redirect_uri");
    const state = url.searchParams.get("state") ?? "";
    const challenge = url.searchParams.get("code_challenge") ?? "";
    if (
      redirectUri !== ALLOWED_REDIRECT ||
      url.searchParams.get("response_type") !== "code" ||
      url.searchParams.get("code_challenge_method") !== "S256" ||
      !challenge
    ) {
      json(response, 400, { error: "invalid_request" });
      return;
    }
    const code = randomUUID();
    codes.set(code, {
      challenge,
      nonce: url.searchParams.get("nonce") ?? "",
      clientId: url.searchParams.get("client_id") ?? "",
      redirectUri,
    });
    const target = new URL(redirectUri);
    target.searchParams.set("code", code);
    target.searchParams.set("state", state);
    response.writeHead(302, { location: target.toString() });
    response.end();
    return;
  }
  if (url.pathname === "/token" && request.method === "POST") {
    let raw = "";
    request.on("data", (chunk) => (raw += chunk));
    request.on("end", () => {
      const form = new URLSearchParams(raw);
      const record = codes.get(form.get("code") ?? "");
      codes.delete(form.get("code") ?? "");
      const verifier = form.get("code_verifier") ?? "";
      const computed = base64Url(
        createHash("sha256").update(verifier).digest(),
      );
      if (
        !record ||
        form.get("grant_type") !== "authorization_code" ||
        form.get("redirect_uri") !== record.redirectUri ||
        computed !== record.challenge
      ) {
        json(response, 400, { error: "invalid_grant" });
        return;
      }
      const now = Math.floor(Date.now() / 1000);
      json(response, 200, {
        token_type: "Bearer",
        expires_in: 300,
        access_token: signJwt({
          iss: ISSUER,
          aud: AUDIENCE,
          sub: SUBJECT,
          iat: now,
          exp: now + 300,
          name: "Development Agent",
          email: "agent@example.invalid",
        }),
        id_token: signJwt({
          iss: ISSUER,
          aud: record.clientId,
          sub: SUBJECT,
          iat: now,
          exp: now + 300,
          nonce: record.nonce,
        }),
      });
    });
    return;
  }
  json(response, 404, { error: "not_found" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`oidc-stub-idp listening on ${ISSUER}`);
});
