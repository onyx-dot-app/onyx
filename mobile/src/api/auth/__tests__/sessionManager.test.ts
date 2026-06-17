// SessionManager unit tests — the tricky pure logic that warrants coverage:
// the single-flight refresh (concurrent callers collapse to one network call),
// the login/logout cache-purge invariants, and the session-epoch guard that
// stops a late refresh from resurrecting a logged-out session. Everything
// touching a native module (HTTP, keychain, MMKV cache, the zustand store) is
// mocked so the test runs as plain logic with no device dependencies.
//
// Globals are imported explicitly from `@jest/globals` so the app's TS config
// stays free of ambient test types.
import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";

import { getToken, setToken } from "@/api/auth/tokenStore";
import {
  __resetSessionStateForTests,
  type BearerTokenResponse,
  getValidToken,
  login,
  logout,
  refreshToken,
} from "@/api/auth/sessionManager";
import { apiFetch, type ApiFetchInit } from "@/api/client";
import { ApiError } from "@/api/errors";
import { persister, queryClient } from "@/query/client";

// `jest.mock` calls are hoisted above the imports by babel-jest, so the mocks
// are registered before the module under test is loaded (despite the source
// order here). Mocking the whole `@/state/session` / `@/query/client` modules
// also keeps their native deps (MMKV) out of the test entirely.
jest.mock("@/api/client");
jest.mock("@/api/auth/tokenStore");
jest.mock("@/query/client", () => ({
  queryClient: { clear: jest.fn() },
  persister: { removeClient: jest.fn() },
}));
jest.mock("@/state/session", () => ({
  useSession: { getState: () => ({ setStatus: jest.fn() }) },
}));

// `apiFetch` is generic (`<T>`), which makes jest.mocked()'s mockResolvedValue /
// mockImplementation infer `never`. Cast each handle to a concrete, non-generic
// Mock signature so the matchers and resolved values type cleanly.
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

const token = (access: string): BearerTokenResponse => ({
  access_token: access,
  token_type: "bearer",
});

beforeEach(() => {
  jest.clearAllMocks();
  // Reset the module-level session epoch + single-flight handle so a test can't
  // leak state (e.g. a non-null inFlightRefresh) into the next one.
  __resetSessionStateForTests();
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
    expect(path).toBe("/api/auth/mobile/login");
    expect(init?.method).toBe("POST");
    expect(init?.auth).toBe(false);
    const body = init?.body as URLSearchParams;
    expect(body).toBeInstanceOf(URLSearchParams);
    expect(body.get("username")).toBe("a@example.com");
    expect(body.get("password")).toBe("pw");

    expect(mockSetToken).toHaveBeenCalledWith("tok-login");
    // Token must be installed BEFORE the cache is purged, so a query firing
    // mid-purge reads the new identity's token, not the prior user's.
    expect(mockSetToken.mock.invocationCallOrder[0]).toBeLessThan(
      mockClear.mock.invocationCallOrder[0],
    );
    expect(mockClear).toHaveBeenCalledTimes(1);
    expect(mockRemoveClient).toHaveBeenCalledTimes(1);
  });
});

describe("logout", () => {
  it("revokes server-side, then wipes the token + query cache", async () => {
    mockApiFetch.mockResolvedValue(undefined);

    await logout();

    expect(mockApiFetch).toHaveBeenCalledWith("/api/auth/mobile/logout", {
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

    // The failure is surfaced (traceable) rather than silently swallowed...
    expect(warnSpy).toHaveBeenCalledWith(expect.any(String), revocationError);
    // ...and the local wipe still runs regardless of the network outcome.
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

    // Three near-simultaneous refresh triggers.
    const p1 = refreshToken();
    const p2 = refreshToken();
    const p3 = refreshToken();

    // Only the first issued a request; the others shared the in-flight promise.
    expect(mockApiFetch).toHaveBeenCalledTimes(1);

    resolveFetch(token("tok-refresh"));
    const [r1, r2, r3] = await Promise.all([p1, p2, p3]);

    expect(r1).toBe("tok-refresh");
    expect(r2).toBe("tok-refresh");
    expect(r3).toBe("tok-refresh");
    expect(mockSetToken).toHaveBeenCalledTimes(1);
    expect(mockSetToken).toHaveBeenCalledWith("tok-refresh");
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
    mockApiFetch.mockRejectedValue(new ApiError({ status: 500 }));

    await expect(refreshToken()).rejects.toBeInstanceOf(ApiError);

    expect(mockSetToken).not.toHaveBeenCalledWith(null);
    expect(mockClear).not.toHaveBeenCalled();
  });

  it("does not resurrect the session when a logout completes mid-refresh", async () => {
    let resolveRefresh!: (value: BearerTokenResponse) => void;
    mockApiFetch.mockImplementation((path) => {
      if (path === "/api/auth/mobile/refresh") {
        return new Promise<BearerTokenResponse>((resolve) => {
          resolveRefresh = resolve;
        });
      }
      return Promise.resolve(undefined); // logout call
    });

    const refreshP = refreshToken(); // in flight
    await logout(); // completes: clears token + bumps the session epoch

    resolveRefresh(token("tok-late")); // refresh resolves AFTER logout
    await expect(refreshP).resolves.toBeNull();

    // The late token must NOT be written back over the logged-out session.
    expect(mockSetToken).not.toHaveBeenCalledWith("tok-late");
    expect(mockSetToken).toHaveBeenLastCalledWith(null);
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

    rejectFetch(new ApiError({ status: 500 })); // transient

    // refresh propagates the transient error; getValidToken must not.
    await expect(refreshP).rejects.toBeInstanceOf(ApiError);
    await expect(validP).resolves.toBe("stored-tok");
  });
});
