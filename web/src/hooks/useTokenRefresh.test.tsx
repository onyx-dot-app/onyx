import { act, renderHook, waitFor } from "@testing-library/react";
import { useTokenRefresh } from "@/hooks/useTokenRefresh";
import { AuthTypeMetadata } from "@/hooks/useAuthTypeMetadata";
import { AuthType } from "@/lib/constants";
import { User } from "@/lib/types";

const baseAuthMetadata = (authType: AuthType): AuthTypeMetadata => ({
  authType,
  autoRedirect: false,
  requiresVerification: false,
  anonymousUserEnabled: null,
  passwordMinLength: 0,
  hasUsers: true,
  oauthEnabled: false,
});

const fakeUser = { id: "user-1" } as User;

describe("useTokenRefresh", () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200 });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  test("does not call /api/auth/refresh while auth type metadata is loading", () => {
    renderHook(() =>
      useTokenRefresh(
        fakeUser,
        baseAuthMetadata(AuthType.BASIC),
        true,
        jest.fn()
      )
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("does not call /api/auth/refresh for SAML deployments", () => {
    renderHook(() =>
      useTokenRefresh(
        fakeUser,
        baseAuthMetadata(AuthType.SAML),
        false,
        jest.fn()
      )
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("does not call /api/auth/refresh for OIDC deployments", () => {
    renderHook(() =>
      useTokenRefresh(
        fakeUser,
        baseAuthMetadata(AuthType.OIDC),
        false,
        jest.fn()
      )
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("calls /api/auth/refresh once when auth type is BASIC and user is present", async () => {
    renderHook(() =>
      useTokenRefresh(
        fakeUser,
        baseAuthMetadata(AuthType.BASIC),
        false,
        jest.fn()
      )
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
  });

  test("does not loop when /api/auth/refresh returns 404 and parent re-renders", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404 });
    const onRefreshFail = jest.fn().mockResolvedValue(undefined);

    const { rerender } = renderHook(
      ({ user }: { user: User }) =>
        useTokenRefresh(
          user,
          baseAuthMetadata(AuthType.BASIC),
          false,
          onRefreshFail
        ),
      { initialProps: { user: { ...fakeUser } } }
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    // Simulate the parent re-render storm that occurs when onRefreshFail
    // -> mutateUser produces a new user object identity.
    for (let i = 0; i < 10; i++) {
      await act(async () => {
        rerender({ user: { ...fakeUser } });
      });
    }

    // The time-gate should suppress every follow-up attempt; the original
    // bug fired ~one extra call per re-render.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
