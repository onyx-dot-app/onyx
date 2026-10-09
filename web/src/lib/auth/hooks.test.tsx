import { act, renderHook, waitFor } from "@testing-library/react";
import { setDocumentVisibility } from "@tests/setup/test-utils";
import { useTokenRefresh } from "@/lib/auth/hooks";
import { User } from "@/lib/types";

const fakeUser = { id: "user-1" } as User;

describe("useTokenRefresh", () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200 });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  test("does not call /api/auth/refresh while auth type metadata is loading", () => {
    renderHook(() => useTokenRefresh(fakeUser, true, jest.fn()));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("calls /api/auth/refresh once when user is present", async () => {
    renderHook(() => useTokenRefresh(fakeUser, false, jest.fn()));

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
      ({ user }: { user: User }) => useTokenRefresh(user, false, onRefreshFail),
      { initialProps: { user: { ...fakeUser } } }
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    for (let i = 0; i < 10; i++) {
      await act(async () => {
        rerender({ user: { ...fakeUser } });
      });
    }

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("hidden tabs do not refresh; returning to visibility catches up", async () => {
    jest.useFakeTimers();
    try {
      setDocumentVisibility(false);
      renderHook(() => useTokenRefresh(fakeUser, false, jest.fn()));

      await act(async () => {
        jest.advanceTimersByTime(31 * 60 * 1000);
      });
      expect(fetchMock).not.toHaveBeenCalled();

      await act(async () => {
        setDocumentVisibility(true);
        document.dispatchEvent(new Event("visibilitychange"));
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
      setDocumentVisibility(true);
    }
  });
});
