import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";

import { getToken, setToken } from "@/api/auth/tokenStore";
import {
  __resetSessionStateForTests,
  type BearerTokenResponse,
  getValidToken,
  login,
  logout,
  PostRegisterLoginError,
  refreshToken,
  register,
} from "@/api/auth/sessionManager";
import { runBrowserSso } from "@/api/auth/browserSso";
import type { ProviderDescriptor } from "@/api/auth/providers";
import { apiFetch, type ApiFetchInit } from "@/api/client";
import { ApiError } from "@/api/errors";
import { persister, queryClient } from "@/query/client";

// babel-jest hoists `jest.mock` above the imports, so these can sit below the import block.
jest.mock("@/api/client");
jest.mock("@/api/auth/tokenStore");
jest.mock("@/api/auth/browserSso");
jest.mock("@/query/client", () => ({
  queryClient: { clear: jest.fn() },
  persister: { removeClient: jest.fn() },
}));
// `mock`-prefixed and read lazily so the hoisted factory can close over it.
let mockServerUrl: string | null = "https://a.test";
jest.mock("@/state/session", () => ({
  useSession: { getState: () => ({ setStatus: jest.fn() }) },
  getStoredServerUrl: () => mockServerUrl,
}));

// generic `apiFetch<T>` makes jest.mocked() infer `never`; cast to a concrete Mock signature.
const mockApiFetch = apiFetch as unknown as Mock<
  (path: string, init?: ApiFetchInit) => Promise<unknown>
>;
const mockGetToken = getToken as unknown as Mock<() => Promise<string | null>>;
const mockSetToken = setToken as unknown as Mock<
  (token: string | null) => Promise<undefined>
>;
const mockClear = queryClient.clear as unknown as Mock<() => void>;
const mockRemoveClient = persister.removeClient as unknown as Mock<
  () => Promise<undefined>
>;
const mockRunBrowserSso = runBrowserSso as unknown as Mock<
  () => Promise<{ code: string; codeVerifier: string }>
>;

const GOOGLE: ProviderDescriptor = {
  id: "google",
  label: "Google",
  kind: "browser",
  authorizePath: "/auth/mobile/oauth/authorize",
};

const token = (access: string): BearerTokenResponse => ({
  access_token: access,
  token_type: "bearer",
});

beforeEach(() => {
  jest.clearAllMocks();
  __resetSessionStateForTests();
  mockServerUrl = "https://a.test";
  mockSetToken.mockResolvedValue(undefined);
  mockGetToken.mockResolvedValue(null);
  mockRemoveClient.mockResolvedValue(undefined);
});

describe("login", () => {
  it("posts form-encoded credentials, stores the token, then purges the cache", async () => {
    mockApiFetch.mockResolvedValue(token("tok-login"));

    await login({ kind: "password", email: "a@example.com", password: "pw" });

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    const [path, init] = mockApiFetch.mock.calls[0];
    expect(path).toBe("/auth/mobile/login");
    expect(init?.method).toBe("POST");
    expect(init?.auth).toBe(false);
    const body = init?.body as URLSearchParams;
    expect(body).toBeInstanceOf(URLSearchParams);
    expect(body.get("username")).toBe("a@example.com");
    expect(body.get("password")).toBe("pw");

    expect(mockSetToken).toHaveBeenCalledWith("tok-login");
    // Token installed BEFORE cache purge, so a query firing mid-purge reads the new token.
    expect(mockSetToken.mock.invocationCallOrder[0]).toBeLessThan(
      mockClear.mock.invocationCallOrder[0],
    );
    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockRemoveClient).toHaveBeenCalledTimes(1);
  });
});

describe("login (browser SSO)", () => {
  it("exchanges the one-time code + verifier, stores the token, then purges the cache", async () => {
    mockRunBrowserSso.mockResolvedValue({
      code: "one-time-code",
      codeVerifier: "the-verifier",
    });
    mockApiFetch.mockResolvedValue(token("tok-sso"));

    await login({ kind: "browser", provider: GOOGLE });

    expect(mockRunBrowserSso).toHaveBeenCalledWith(GOOGLE);
    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    const [path, init] = mockApiFetch.mock.calls[0];
    expect(path).toBe("/auth/mobile/sso/exchange");
    expect(init?.method).toBe("POST");
    expect(init?.auth).toBe(false);
    expect(init?.body).toEqual({
      code: "one-time-code",
      code_verifier: "the-verifier",
    });

    expect(mockSetToken).toHaveBeenCalledWith("tok-sso");
    expect(mockSetToken.mock.invocationCallOrder[0]).toBeLessThan(
      mockClear.mock.invocationCallOrder[0],
    );
    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockRemoveClient).toHaveBeenCalledTimes(1);
  });

  it("does not exchange or store a token when the browser flow fails/cancels", async () => {
    mockRunBrowserSso.mockRejectedValue(new Error("cancelled"));

    await expect(
      login({ kind: "browser", provider: GOOGLE }),
    ).rejects.toThrow();

    expect(mockApiFetch).not.toHaveBeenCalled();
    expect(mockSetToken).not.toHaveBeenCalled();
  });
});

describe("register", () => {
  it("creates the account as JSON, then logs in to mint the token", async () => {
    mockApiFetch.mockImplementation((path) =>
      Promise.resolve(path === "/auth/register" ? undefined : token("tok-new")),
    );

    await register({ email: "a@example.com", password: "pw" });

    const [registerPath, registerInit] = mockApiFetch.mock.calls[0];
    expect(registerPath).toBe("/auth/register");
    expect(registerInit?.method).toBe("POST");
    expect(registerInit?.auth).toBe(false);
    expect(registerInit?.body).toEqual({
      email: "a@example.com",
      password: "pw",
    });

    expect(mockApiFetch.mock.calls[1][0]).toBe("/auth/mobile/login");
    expect(mockSetToken).toHaveBeenCalledWith("tok-new");
  });

  it("does not log in when account creation fails", async () => {
    mockApiFetch.mockRejectedValueOnce(new ApiError({ status: 400 }));

    await expect(
      register({ email: "taken@example.com", password: "pw" }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(mockSetToken).not.toHaveBeenCalled();
  });

  it("flags a post-register login failure distinctly (the account exists)", async () => {
    mockApiFetch.mockImplementation((path) =>
      path === "/auth/register"
        ? Promise.resolve(undefined)
        : Promise.reject(new ApiError({ status: 400 })),
    );

    await expect(
      register({ email: "a@example.com", password: "pw" }),
    ).rejects.toBeInstanceOf(PostRegisterLoginError);
    expect(mockSetToken).not.toHaveBeenCalled();
  });
});

describe("logout", () => {
  it("revokes server-side, then wipes the token + query cache", async () => {
    mockApiFetch.mockResolvedValue(undefined);

    await logout();

    expect(mockApiFetch).toHaveBeenCalledWith("/auth/mobile/logout", {
      method: "POST",
    });
    expect(mockSetToken).toHaveBeenCalledWith(null);
    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockRemoveClient).toHaveBeenCalledTimes(1);
  });

  it("logs, then still wipes locally, when server revocation fails", async () => {
    const revocationError = new ApiError({ status: 500 });
    mockApiFetch.mockRejectedValue(revocationError);
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});

    await logout();

    expect(warnSpy).toHaveBeenCalledWith(expect.any(String), revocationError);
    expect(mockSetToken).toHaveBeenCalledWith(null);
    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockRemoveClient).toHaveBeenCalledTimes(1);

    warnSpy.mockRestore();
  });
});

describe("refreshToken (single-flight)", () => {
  it("collapses concurrent callers into one network request", async () => {
    let resolveFetch!: (value: BearerTokenResponse) => void;
    mockApiFetch.mockReturnValue(
      new Promise<BearerTokenResponse>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const p1 = refreshToken();
    const p2 = refreshToken();
    const p3 = refreshToken();

    expect(mockApiFetch).toHaveBeenCalledTimes(1);

    resolveFetch(token("tok-refresh"));
    const [r1, r2, r3] = await Promise.all([p1, p2, p3]);

    expect(r1).toBe("tok-refresh");
    expect(r2).toBe("tok-refresh");
    expect(r3).toBe("tok-refresh");
    expect(mockSetToken).toHaveBeenCalledTimes(1);
    expect(mockSetToken).toHaveBeenCalledWith("tok-refresh");
  });

  it("sends the refresh with the stored token so it can't await its own promise", async () => {
    mockApiFetch.mockResolvedValueOnce(token("tok-a"));

    await refreshToken();

    expect(mockApiFetch).toHaveBeenCalledWith(
      "/auth/mobile/refresh",
      expect.objectContaining({ auth: "stored" }),
    );
  });

  it("starts a fresh request after the previous refresh settles", async () => {
    mockApiFetch.mockResolvedValueOnce(token("tok-a"));
    await refreshToken();
    mockApiFetch.mockResolvedValueOnce(token("tok-b"));
    await refreshToken();

    expect(mockApiFetch).toHaveBeenCalledTimes(2);
  });

  it("clears the session and returns null on an auth error", async () => {
    mockApiFetch.mockRejectedValue(new ApiError({ status: 401 }));

    const result = await refreshToken();

    expect(result).toBeNull();
    expect(mockSetToken).toHaveBeenCalledWith(null);
    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockRemoveClient).toHaveBeenCalledTimes(1);
  });

  it("re-throws a transient error without dropping the token", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    mockApiFetch.mockRejectedValue(new ApiError({ status: 500 }));

    await expect(refreshToken()).rejects.toBeInstanceOf(ApiError);

    expect(mockSetToken).not.toHaveBeenCalledWith(null);
    expect(mockClear).not.toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  it("still answers null when clearing the session fails after a rejected token", async () => {
    /*
     * A throw from inside the catch escapes it, so this used to reject instead — reaching the
     * fire-and-forget refresh loop as an unlogged rejection with the session half-cleared.
     */
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    const clearFailure = new Error("keychain unavailable");
    mockApiFetch.mockRejectedValue(new ApiError({ status: 401 }));
    mockSetToken.mockRejectedValue(clearFailure);

    await expect(refreshToken()).resolves.toBeNull();
    expect(warnSpy).toHaveBeenCalledWith(expect.any(String), clearFailure);

    warnSpy.mockRestore();
  });

  it("logs a transient failure once, however many callers were waiting on it", async () => {
    /*
     * Every caller swallows this rejection, so this line is the only trace a session that dies
     * from repeated failed refreshes ever leaves.
     */
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    mockGetToken.mockResolvedValue("stored-tok");
    const failure = new ApiError({ status: 500 });
    let rejectFetch!: (reason: unknown) => void;
    mockApiFetch.mockReturnValue(
      new Promise<BearerTokenResponse>((_resolve, reject) => {
        rejectFetch = reject;
      }),
    );

    const refreshP = refreshToken();
    const waiters = [getValidToken(), getValidToken(), getValidToken()];
    rejectFetch(failure);

    await expect(refreshP).rejects.toBe(failure);
    await expect(Promise.all(waiters)).resolves.toEqual([
      "stored-tok",
      "stored-tok",
      "stored-tok",
    ]);

    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(expect.any(String), failure);

    warnSpy.mockRestore();
  });

  it("does not resurrect the session when a logout completes mid-refresh", async () => {
    let resolveRefresh!: (value: BearerTokenResponse) => void;
    mockApiFetch.mockImplementation((path) => {
      if (path === "/auth/mobile/refresh") {
        return new Promise<BearerTokenResponse>((resolve) => {
          resolveRefresh = resolve;
        });
      }
      return Promise.resolve(undefined);
    });

    const refreshP = refreshToken();
    await logout(); // bumps the session epoch

    resolveRefresh(token("tok-late"));
    await expect(refreshP).resolves.toBeNull();

    expect(mockSetToken).not.toHaveBeenCalledWith("tok-late");
    expect(mockSetToken).toHaveBeenLastCalledWith(null);
  });

  it("discards a refresh that lands after the user switched instances", async () => {
    let resolveRefresh!: (value: BearerTokenResponse) => void;
    mockApiFetch.mockReturnValue(
      new Promise<BearerTokenResponse>((resolve) => {
        resolveRefresh = resolve;
      }),
    );

    const refreshP = refreshToken();
    // The connect screen swaps instances without touching the session epoch.
    mockServerUrl = "https://b.test";
    resolveRefresh(token("tok-instance-a"));

    await expect(refreshP).resolves.toBeNull();
    /*
     * `setToken` keys off the *current* URL, so writing here would file instance A's bearer under
     * instance B's key and hand it to a different server on the next request.
     */
    expect(mockSetToken).not.toHaveBeenCalledWith("tok-instance-a");
  });

  it("leaves the new instance's session alone when the old one's refresh is rejected", async () => {
    let rejectRefresh!: (reason: unknown) => void;
    mockApiFetch.mockReturnValue(
      new Promise<BearerTokenResponse>((_resolve, reject) => {
        rejectRefresh = reject;
      }),
    );

    const refreshP = refreshToken();
    mockServerUrl = "https://b.test";
    rejectRefresh(new ApiError({ status: 401 }));

    await expect(refreshP).resolves.toBeNull();
    // A dead token on instance A says nothing about B; wiping would sign the user out of B.
    expect(mockClear).not.toHaveBeenCalled();
    expect(mockSetToken).not.toHaveBeenCalledWith(null);
  });
});

describe("getValidToken", () => {
  it("returns the stored token when no refresh is in flight", async () => {
    mockGetToken.mockResolvedValue("stored-tok");

    await expect(getValidToken()).resolves.toBe("stored-tok");
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("shares the in-flight refresh instead of reading the stale token", async () => {
    let resolveFetch!: (value: BearerTokenResponse) => void;
    mockApiFetch.mockReturnValue(
      new Promise<BearerTokenResponse>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const refreshP = refreshToken();
    const validP = getValidToken();

    resolveFetch(token("tok-shared"));

    await expect(validP).resolves.toBe("tok-shared");
    await expect(refreshP).resolves.toBe("tok-shared");
    expect(mockGetToken).not.toHaveBeenCalled();
  });

  it("falls back to the stored token when an in-flight refresh fails transiently", async () => {
    mockGetToken.mockResolvedValue("stored-tok");
    let rejectFetch!: (reason: unknown) => void;
    mockApiFetch.mockReturnValue(
      new Promise<BearerTokenResponse>((_resolve, reject) => {
        rejectFetch = reject;
      }),
    );

    const refreshP = refreshToken();
    const validP = getValidToken();

    rejectFetch(new ApiError({ status: 500 }));

    await expect(refreshP).rejects.toBeInstanceOf(ApiError);
    await expect(validP).resolves.toBe("stored-tok");
  });
});
