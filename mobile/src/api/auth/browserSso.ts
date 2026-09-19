// Authorize URL is OPENED, never fetched — else the CSRF cookie sets on the wrong client.
// Only `code_challenge` rides the URL; `code_verifier` stays on-device until the exchange.
import * as Crypto from "expo-crypto";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";

import { getApiPrefix } from "@/api/config";
import type { ProviderDescriptor } from "@/api/auth/providers";
import { getStoredServerUrl } from "@/state/session";

// Must match app.json's `scheme` + the backend's MOBILE_ALLOWED_REDIRECT_URIS allowlist.
export const MOBILE_REDIRECT_URI = "onyx://auth/callback";

export interface BrowserSsoResult {
  code: string;
  codeVerifier: string;
}

export class BrowserSsoCancelledError extends Error {
  constructor() {
    super("Sign-in was cancelled.");
    this.name = "BrowserSsoCancelledError";
  }
}

const B64URL_ALPHABET =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

// Hand-rolled: Hermes has no reliable `btoa`.
function base64UrlFromBytes(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : undefined;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : undefined;
    out += B64URL_ALPHABET[b0 >> 2];
    out += B64URL_ALPHABET[((b0 & 0x03) << 4) | ((b1 ?? 0) >> 4)];
    if (b1 === undefined) break;
    out += B64URL_ALPHABET[((b1 & 0x0f) << 2) | ((b2 ?? 0) >> 6)];
    if (b2 === undefined) break;
    out += B64URL_ALPHABET[b2 & 0x3f];
  }
  return out;
}

// Must byte-match the backend's compute_s256_challenge, else every exchange 401s.
function standardToUrlBase64(value: string): string {
  return value.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface PkcePair {
  verifier: string;
  challenge: string;
}

async function generatePkcePair(): Promise<PkcePair> {
  const verifier = base64UrlFromBytes(await Crypto.getRandomBytesAsync(32));
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    verifier,
    { encoding: Crypto.CryptoEncoding.BASE64 },
  );
  return { verifier, challenge: standardToUrlBase64(digest) };
}

function buildAuthorizeUrl(
  serverUrl: string,
  authorizePath: string,
  state: string,
  codeChallenge: string,
): string {
  const params = new URLSearchParams({
    redirect: "true",
    mobile_redirect_uri: MOBILE_REDIRECT_URI,
    app_state: state,
    app_code_challenge: codeChallenge,
  });
  const base = serverUrl.replace(/\/+$/, "");
  return `${base}${getApiPrefix()}${authorizePath}?${params.toString()}`;
}

export async function runBrowserSso(
  descriptor: ProviderDescriptor,
): Promise<BrowserSsoResult> {
  const serverUrl = getStoredServerUrl();
  if (!serverUrl) {
    throw new Error("Connect to an Onyx instance before signing in.");
  }
  if (!descriptor.authorizePath) {
    throw new Error(`Provider ${descriptor.id} has no authorize endpoint.`);
  }

  const state = base64UrlFromBytes(await Crypto.getRandomBytesAsync(16));
  const { verifier, challenge } = await generatePkcePair();
  const authorizeUrl = buildAuthorizeUrl(
    serverUrl,
    descriptor.authorizePath,
    state,
    challenge,
  );

  const result = await WebBrowser.openAuthSessionAsync(
    authorizeUrl,
    MOBILE_REDIRECT_URI,
  );

  if (
    result.type === WebBrowser.WebBrowserResultType.CANCEL ||
    result.type === WebBrowser.WebBrowserResultType.DISMISS
  ) {
    throw new BrowserSsoCancelledError();
  }
  if (result.type !== "success") {
    throw new Error("Couldn't complete sign-in. Please try again.");
  }

  const { queryParams } = Linking.parse(result.url);
  const returnedState = queryParams?.state;
  const code = queryParams?.code;

  // CSRF nonce; plain compare is fine.
  if (typeof returnedState !== "string" || returnedState !== state) {
    throw new Error("Sign-in could not be verified. Please try again.");
  }
  if (typeof code !== "string" || code.length === 0) {
    throw new Error("Couldn't complete sign-in. Please try again.");
  }

  return { code, codeVerifier: verifier };
}
