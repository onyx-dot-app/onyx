// digestStringAsync delegates to node's real SHA-256 so the S256-match assertion is meaningful.
import { createHash } from "crypto";

import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";

import { runBrowserSso, BrowserSsoCancelledError } from "@/api/auth/browserSso";
import type { ProviderDescriptor } from "@/api/auth/providers";
import { openAuthSessionAsync } from "expo-web-browser";

// `jest.mock` is hoisted above the imports by babel-jest.
jest.mock("@/api/config", () => ({ getApiPrefix: () => "/api" }));
jest.mock("@/state/session", () => ({
  getStoredServerUrl: () => "https://acme.onyx.app",
}));

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  CryptoEncoding: { BASE64: "base64", HEX: "hex" },
  // Deterministic bytes so the verifier is stable across a run.
  getRandomBytesAsync: jest.fn((n: number) =>
    Promise.resolve(
      Uint8Array.from({ length: n }, (_, i) => (i * 31 + 7) & 0xff),
    ),
  ),
  // Real SHA-256, standard-base64 (what expo returns); `require` since jest forbids out-of-scope imports here.
  digestStringAsync: jest.fn((_algo: string, data: string) =>
    Promise.resolve(
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      (require("crypto") as typeof import("crypto"))
        .createHash("sha256")
        .update(data)
        .digest("base64"),
    ),
  ),
}));

jest.mock("expo-web-browser", () => ({
  WebBrowserResultType: {
    CANCEL: "cancel",
    DISMISS: "dismiss",
    OPENED: "opened",
    LOCKED: "locked",
  },
  openAuthSessionAsync: jest.fn(),
}));

jest.mock("expo-linking", () => ({
  // Mirror expo-linking's parse for a custom-scheme URL: pull the query string.
  parse: (url: string) => ({
    queryParams: Object.fromEntries(new URL(url).searchParams.entries()),
  }),
}));

const GOOGLE: ProviderDescriptor = {
  id: "google",
  label: "Google",
  kind: "browser",
  authorizePath: "/auth/mobile/oauth/authorize",
};

const mockOpen = openAuthSessionAsync as unknown as Mock<
  (
    url: string,
    redirectUrl?: string | null,
  ) => Promise<{ type: string; url?: string }>
>;

function toBase64Url(standardBase64: string): string {
  return standardBase64
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("runBrowserSso", () => {
  it("opens the authorize URL with redirect=true + PKCE challenge, and returns the code", async () => {
    // Echo app_state back, like the backend's 302.
    let openedUrl = "";
    mockOpen.mockImplementation((url) => {
      openedUrl = url;
      const state = new URL(url).searchParams.get("app_state");
      return Promise.resolve({
        type: "success",
        url: `onyx://auth/callback?code=ONE_TIME_CODE&state=${state}`,
      });
    });

    const result = await runBrowserSso(GOOGLE);

    expect(result.code).toBe("ONE_TIME_CODE");
    expect(result.codeVerifier.length).toBeGreaterThan(0);

    const opened = new URL(openedUrl);
    expect(opened.origin + opened.pathname).toBe(
      "https://acme.onyx.app/api/auth/mobile/oauth/authorize",
    );
    expect(opened.searchParams.get("redirect")).toBe("true");
    expect(opened.searchParams.get("mobile_redirect_uri")).toBe(
      "onyx://auth/callback",
    );
    expect(mockOpen.mock.calls[0][1]).toBe("onyx://auth/callback");

    // Challenge on the wire == S256(verifier); the backend recomputes the same.
    const expectedChallenge = toBase64Url(
      createHash("sha256").update(result.codeVerifier).digest("base64"),
    );
    expect(opened.searchParams.get("app_code_challenge")).toBe(
      expectedChallenge,
    );
  });

  it("never puts the code_verifier on the authorize URL (only the challenge)", async () => {
    let openedUrl = "";
    mockOpen.mockImplementation((url) => {
      openedUrl = url;
      const state = new URL(url).searchParams.get("app_state");
      return Promise.resolve({
        type: "success",
        url: `onyx://auth/callback?code=c&state=${state}`,
      });
    });

    const result = await runBrowserSso(GOOGLE);

    expect(openedUrl).toContain("app_code_challenge=");
    expect(openedUrl).not.toContain(result.codeVerifier);
  });

  it("rejects a callback whose state doesn't match the one it generated", async () => {
    mockOpen.mockResolvedValue({
      type: "success",
      url: "onyx://auth/callback?code=c&state=ATTACKER_STATE",
    });

    await expect(runBrowserSso(GOOGLE)).rejects.toThrow();
  });

  it("rejects a success callback with no code", async () => {
    mockOpen.mockImplementation((url) => {
      const state = new URL(url).searchParams.get("app_state");
      return Promise.resolve({
        type: "success",
        url: `onyx://auth/callback?state=${state}`,
      });
    });

    await expect(runBrowserSso(GOOGLE)).rejects.toThrow();
  });

  it("raises BrowserSsoCancelledError when the user cancels the browser", async () => {
    mockOpen.mockResolvedValue({ type: "cancel" });

    await expect(runBrowserSso(GOOGLE)).rejects.toBeInstanceOf(
      BrowserSsoCancelledError,
    );
  });

  it("raises BrowserSsoCancelledError when the browser is dismissed", async () => {
    mockOpen.mockResolvedValue({ type: "dismiss" });

    await expect(runBrowserSso(GOOGLE)).rejects.toBeInstanceOf(
      BrowserSsoCancelledError,
    );
  });
});
