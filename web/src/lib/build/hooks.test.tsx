import { StrictMode } from "react";
import { act, deferred, renderHook, waitFor } from "@tests/setup/test-utils";
import { SWRConfig, useSWRConfig, type State } from "swr";
import {
  useFilePreview,
  useWorkspaceListing,
  useOutputWebapps,
  useOutputCards,
} from "@/lib/build/hooks";
import {
  fetchWebappInfo,
  fetchOutputCards,
  markOutputViewed,
  markOutputsViewed,
} from "@/app/craft/services/apiServices";
import type { OutputCard } from "@/app/craft/types/streamingTypes";
import { SWR_KEYS } from "@/lib/swr-keys";
import { FetchError, skipRetryOnAuthError } from "@/lib/fetcher";

let mockPreviewUserId: string | undefined = "test-user";
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: mockPreviewUserId ? { id: mockPreviewUserId } : null,
  }),
}));
jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchWebappInfo: jest.fn(),
  fetchOutputCards: jest.fn(),
  markOutputViewed: jest.fn(),
  markOutputsViewed: jest.fn(),
}));

it("reports a failed viewed save and retains the unread revision", async () => {
  const card: OutputCard = {
    id: "failed",
    kind: "file",
    path: "outputs/report.md",
    name: "report.md",
    turn_index: 0,
    revision: 1,
    size_bytes: 10,
    deleted: false,
    viewed_revision: null,
  };
  const error = new Error("offline");
  const warning = jest.spyOn(console, "warn").mockImplementation(() => {});
  jest.mocked(fetchOutputCards).mockResolvedValue([card]);
  jest.mocked(markOutputViewed).mockRejectedValueOnce(error);
  const { result } = renderHook(() => useOutputCards("failed-save"));
  await waitFor(() => expect(result.current.cards).toEqual([card]));
  await act(async () => {
    await result.current.markViewed(card);
  });
  expect(result.current.cards).toEqual([card]);
  expect(warning).toHaveBeenCalledWith(
    "Failed to save output viewed revision",
    error
  );
  warning.mockRestore();
});

// Persisted output ownership and viewed revisions.
it("applies a delayed viewed acknowledgement to its original session without reverting a newer revision", async () => {
  const cache = new Map<string, State>();
  const card: OutputCard = {
    id: "a",
    kind: "file",
    path: "outputs/report.md",
    name: "report.md",
    turn_index: 0,
    revision: 1,
    size_bytes: 10,
    deleted: false,
    viewed_revision: null,
  };
  const nextCard = { ...card, revision: 2, turn_index: 1 };
  const other = { ...card, id: "b" };
  const acknowledgement = deferred<OutputCard>();
  jest
    .mocked(fetchOutputCards)
    .mockImplementation(async (id) =>
      id === "session-a" ? [nextCard] : [other]
    );
  jest.mocked(markOutputViewed).mockReturnValue(acknowledgement.promise);
  const { result, rerender } = renderHook(
    ({ id }) => ({ ...useOutputCards(id), mutate: useSWRConfig().mutate }),
    {
      initialProps: { id: "session-a" },
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>
      ),
    }
  );
  await waitFor(() => expect(result.current.cards).toEqual([nextCard]));
  let pending: Promise<void> | undefined;
  act(() => {
    pending = result.current.markViewed(card);
  });
  await act(async () => {
    await result.current.mutate(
      [SWR_KEYS.buildSessionOutputCards("session-a"), "test-user"],
      [nextCard],
      false
    );
  });
  rerender({ id: "session-b" });
  await waitFor(() => expect(result.current.cards).toEqual([other]));
  const requests = jest.mocked(fetchOutputCards).mock.calls.length;
  await act(async () => {
    acknowledgement.resolve({ ...card, viewed_revision: 1 });
    await pending;
  });
  expect(result.current.cards).toEqual([other]);
  expect(fetchOutputCards).toHaveBeenCalledTimes(requests);
  rerender({ id: "session-a" });
  expect(result.current.cards).toEqual([{ ...nextCard, viewed_revision: 1 }]);
  expect(markOutputViewed).toHaveBeenCalledWith("session-a", card);
});

it("marks the loaded revisions in one request without clearing a newer output", async () => {
  const cache = new Map<string, State>();
  const first: OutputCard = {
    id: "a",
    kind: "file",
    path: "outputs/a.md",
    name: "a.md",
    turn_index: 0,
    revision: 1,
    size_bytes: 10,
    deleted: false,
    viewed_revision: null,
  };
  const second = { ...first, id: "b", path: "outputs/b.md" };
  const seen = { ...first, id: "seen", viewed_revision: 1 };
  const removed = { ...first, id: "removed", deleted: true };
  const loaded = [first, second, seen, removed];
  jest.mocked(fetchOutputCards).mockResolvedValue(loaded);
  const acknowledgement = deferred<OutputCard[]>();
  jest.mocked(markOutputsViewed).mockReturnValue(acknowledgement.promise);
  const { result } = renderHook(
    () => ({ ...useOutputCards("bulk"), mutate: useSWRConfig().mutate }),
    {
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>
      ),
    }
  );
  await waitFor(() => expect(result.current.cards).toEqual(loaded));
  let pending: Promise<void> | undefined;
  act(() => {
    pending = result.current.markAllViewed();
  });
  expect(markOutputsViewed).toHaveBeenCalledWith("bulk", [first, second]);
  const newer = { ...first, revision: 2, turn_index: 1 };
  await act(async () => {
    await result.current.mutate(
      [SWR_KEYS.buildSessionOutputCards("bulk"), "test-user"],
      [newer, second],
      false
    );
  });
  jest.mocked(fetchOutputCards).mockResolvedValue([
    { ...newer, viewed_revision: 1 },
    { ...second, viewed_revision: 1 },
  ]);
  await act(async () => {
    acknowledgement.resolve([
      { ...first, viewed_revision: 1 },
      { ...second, viewed_revision: 1 },
    ]);
    await pending;
  });
  expect(result.current.cards[0]).toEqual({ ...newer, viewed_revision: 1 });
});

it("replaces cached bytes across revisions and rejects late responses", async () => {
  const cache = new Map<string, State>();
  const oldRequest = deferred<Blob>();
  const newRequest = deferred<Blob>();
  const load = jest
    .fn<Promise<Blob>, []>()
    .mockReturnValueOnce(oldRequest.promise)
    .mockReturnValueOnce(newRequest.promise);
  const { result, rerender } = renderHook(
    ({ revision }) => useFilePreview("file", load, { revision }),
    {
      initialProps: { revision: "old" },
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>
      ),
    }
  );
  rerender({ revision: "new" });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  const newBlob = new Blob(["new"]);
  await act(async () => newRequest.resolve(newBlob));
  expect(result.current.data).toBe(newBlob);
  await act(async () => oldRequest.resolve(new Blob(["old"])));
  expect(result.current.data).toBe(newBlob);

  for (let revision = 0; revision < 10; revision += 1) {
    const blob = new Blob([String(revision)]);
    load.mockResolvedValueOnce(blob);
    rerender({ revision: String(revision) });
    await waitFor(() => expect(result.current.data).toBe(blob));
    expect(cache.size).toBe(1);
  }
});

it("retries transient failures through the shared SWR policy", async () => {
  jest.useFakeTimers();
  const blob: Blob = new Blob(["recovered"]);
  const failure: FetchError = new FetchError("Unavailable", 503, null);
  const load: jest.Mock<Promise<Blob>, []> = jest
    .fn()
    .mockRejectedValueOnce(failure)
    .mockResolvedValue(blob);
  try {
    const { result } = renderHook(
      () => useFilePreview("retry-file", load, { revision: "v1" }),
      {
        wrapper: function RetryProvider({ children }) {
          return (
            <SWRConfig
              value={{
                provider: () => new Map(),
                onErrorRetry: skipRetryOnAuthError,
              }}
            >
              {children}
            </SWRConfig>
          );
        },
      }
    );
    await act(async () => {});
    expect(result.current.error).toBe(failure);
    expect(result.current.isLoading).toBe(false);
    await act(async () => jest.advanceTimersByTime(4000));
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.data).toBe(blob);
    expect(result.current.error).toBeUndefined();
  } finally {
    jest.useRealTimers();
  }
});

it("hides errors from an older revision while its replacement loads", async () => {
  const replacement: ReturnType<typeof deferred<Blob>> = deferred<Blob>();
  const load: jest.Mock<Promise<Blob>, []> = jest
    .fn()
    .mockRejectedValueOnce(new Error("Old failure"))
    .mockReturnValueOnce(replacement.promise);
  const { result, rerender } = renderHook(
    ({ revision }) => useFilePreview("failed-file", load, { revision }),
    {
      initialProps: { revision: "old" },
      wrapper: function ErrorProvider({ children }) {
        return (
          <SWRConfig
            value={{ provider: () => new Map(), shouldRetryOnError: false }}
          >
            {children}
          </SWRConfig>
        );
      },
    }
  );
  await waitFor(() => expect(result.current.error).toBeDefined());
  rerender({ revision: "new" });
  expect(result.current.error).toBeUndefined();
  expect(result.current.isLoading).toBe(true);
  const blob: Blob = new Blob(["new"]);
  await act(async () => replacement.resolve(blob));
  expect(result.current.data).toBe(blob);
});

it("ignores a late failure after the next revision succeeds", async () => {
  const oldRequest: ReturnType<typeof deferred<Blob>> = deferred<Blob>();
  const blob: Blob = new Blob(["new"]);
  const load: jest.Mock<Promise<Blob>, []> = jest
    .fn()
    .mockReturnValueOnce(oldRequest.promise)
    .mockResolvedValue(blob);
  const { result, rerender } = renderHook(
    ({ revision }) => useFilePreview("late-failure", load, { revision }),
    {
      initialProps: { revision: "old" },
      wrapper: function LateErrorProvider({ children }) {
        return (
          <SWRConfig
            value={{ provider: () => new Map(), shouldRetryOnError: false }}
          >
            {children}
          </SWRConfig>
        );
      },
    }
  );
  rerender({ revision: "new" });
  await waitFor(() => expect(result.current.data).toBe(blob));
  await act(async () => oldRequest.reject(new Error("Old failure")));
  expect(result.current.data).toBe(blob);
  expect(result.current.error).toBeUndefined();
});

it.each([undefined, "known-revision"])(
  "revalidates on activation only without a revision (%s)",
  async (revision) => {
    const replacement = deferred<string>();
    const load = jest
      .fn<Promise<string>, []>()
      .mockResolvedValueOnce("original")
      .mockReturnValueOnce(replacement.promise);
    const { result, rerender } = renderHook(
      ({ isActive }) =>
        useFilePreview("retained", load, { revision, isActive }),
      {
        initialProps: { isActive: true },
        wrapper: function RetainedProvider({ children }) {
          return (
            <SWRConfig value={{ provider: () => new Map() }}>
              {children}
            </SWRConfig>
          );
        },
      }
    );
    await waitFor(() => expect(result.current.data).toBe("original"));
    rerender({ isActive: false });
    expect(load).toHaveBeenCalledTimes(1);
    rerender({ isActive: true });
    expect(result.current.data).toBe("original");
    expect(result.current.isLoading).toBe(revision === undefined);
    expect(load).toHaveBeenCalledTimes(revision === undefined ? 2 : 1);
    await act(async () => replacement.resolve("updated"));
    expect(result.current.data).toBe(
      revision === undefined ? "updated" : "original"
    );
    rerender({ isActive: true });
    expect(load).toHaveBeenCalledTimes(revision === undefined ? 2 : 1);
  }
);

it("retains useful data through pending refresh and failure", async () => {
  const replacement = deferred<string>();
  const load = jest
    .fn<Promise<string>, []>()
    .mockResolvedValueOnce("original")
    .mockReturnValueOnce(replacement.promise);
  const { result, rerender } = renderHook(
    ({ refreshKey }) =>
      useFilePreview("failed-refresh", load, {
        revision: "revision",
        refreshKey,
      }),
    {
      initialProps: { refreshKey: 0 },
      wrapper: function RetainedFailureProvider({ children }) {
        return (
          <SWRConfig
            value={{ provider: () => new Map(), shouldRetryOnError: false }}
          >
            {children}
          </SWRConfig>
        );
      },
    }
  );
  await waitFor(() => expect(result.current.data).toBe("original"));
  rerender({ refreshKey: 1 });
  expect(result.current.data).toBe("original");
  expect(result.current.isLoading).toBe(true);
  await act(async () => replacement.reject(new Error("offline")));
  expect(result.current.data).toBe("original");
  expect(result.current.error?.message).toBe("offline");
  expect(result.current.isLoading).toBe(false);
});

it.each([401, 403, 404])(
  "removes retained file bytes after access or resource loss (%s)",
  async (status) => {
    const load = jest
      .fn<Promise<string>, []>()
      .mockResolvedValueOnce("private file")
      .mockRejectedValueOnce(new FetchError("Unavailable", status, null))
      .mockRejectedValueOnce(new FetchError("Offline", 503, null))
      .mockResolvedValueOnce("new authorized file");
    const { result, rerender } = renderHook(
      ({ refreshKey }) =>
        useFilePreview(`access-loss-${status}`, load, {
          revision: "revision",
          refreshKey,
        }),
      {
        initialProps: { refreshKey: 0 },
        wrapper: function AccessLossProvider({ children }) {
          return (
            <SWRConfig
              value={{ provider: () => new Map(), shouldRetryOnError: false }}
            >
              {children}
            </SWRConfig>
          );
        },
      }
    );
    await waitFor(() => expect(result.current.data).toBe("private file"));
    rerender({ refreshKey: 1 });
    await waitFor(() => expect(result.current.error).toBeDefined());
    expect(result.current.data).toBeUndefined();
    rerender({ refreshKey: 2 });
    await waitFor(() => expect(result.current.error?.message).toBe("Offline"));
    expect(result.current.data).toBeUndefined();
    rerender({ refreshKey: 3 });
    await waitFor(() =>
      expect(result.current.data).toBe("new authorized file")
    );
  }
);

it("defers initial preview reads and revision changes while hidden", async () => {
  const load = jest.fn<Promise<string>, []>().mockResolvedValue("content");
  const { result, rerender } = renderHook(
    ({ revision, isActive }) =>
      useFilePreview("hidden-preview", load, { revision, isActive }),
    {
      initialProps: { revision: "old", isActive: false },
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
      ),
    }
  );
  expect(load).not.toHaveBeenCalled();
  rerender({ revision: "old", isActive: true });
  await waitFor(() => expect(result.current.data).toBe("content"));
  rerender({ revision: "old", isActive: false });
  rerender({ revision: "new", isActive: false });
  expect(load).toHaveBeenCalledTimes(1);
  rerender({ revision: "new", isActive: true });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
});

it("stops scheduled preview retries while hidden and retries a known revision on reopen", async () => {
  jest.useFakeTimers();
  const load = jest
    .fn<Promise<string>, []>()
    .mockRejectedValueOnce(new FetchError("Unavailable", 503, null))
    .mockResolvedValue("recovered");
  try {
    const { result, rerender } = renderHook(
      ({ isActive }) =>
        useFilePreview("hidden-retry", load, { revision: "known", isActive }),
      {
        initialProps: { isActive: true },
        wrapper: ({ children }) => (
          <SWRConfig value={{ provider: () => new Map() }}>
            {children}
          </SWRConfig>
        ),
      }
    );
    await act(async () => {});
    expect(result.current.error).toBeDefined();
    rerender({ isActive: false });
    await act(async () => jest.advanceTimersByTime(4000));
    expect(load).toHaveBeenCalledTimes(1);
    rerender({ isActive: true });
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.data).toBe("recovered");
  } finally {
    jest.useRealTimers();
  }
});

it("accepts an in-flight preview result while hidden and reuses it on reopen", async () => {
  const pending = deferred<string>();
  const load = jest.fn<Promise<string>, []>().mockReturnValue(pending.promise);
  const { result, rerender } = renderHook(
    ({ isActive }) =>
      useFilePreview("hidden-completion", load, {
        revision: "known",
        isActive,
      }),
    {
      initialProps: { isActive: true },
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
      ),
    }
  );
  rerender({ isActive: false });
  await act(async () => pending.resolve("finished"));
  expect(result.current.data).toBe("finished");
  rerender({ isActive: true });
  expect(load).toHaveBeenCalledTimes(1);
  expect(result.current.data).toBe("finished");
});

it("reuses matching revisions across remounts and refreshes changed revisions", async () => {
  const cache = new Map<string, State>();
  const load = jest.fn().mockResolvedValue("cached thumbnail");
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>
  );
  const first = renderHook(
    () => useFilePreview("thumbnail", load, { revision: "v1" }),
    { wrapper }
  );
  await waitFor(() =>
    expect(first.result.current.data).toBe("cached thumbnail")
  );
  first.unmount();
  const second = renderHook(
    () => useFilePreview("thumbnail", load, { revision: "v1" }),
    { wrapper }
  );
  expect(second.result.current.data).toBe("cached thumbnail");
  expect(load).toHaveBeenCalledTimes(1);
  second.unmount();
  load.mockResolvedValue("updated thumbnail");
  const third = renderHook(
    () => useFilePreview("thumbnail", load, { revision: "v2" }),
    { wrapper }
  );
  await waitFor(() =>
    expect(third.result.current.data).toBe("updated thumbnail")
  );
  expect(load).toHaveBeenCalledTimes(2);
});

it("keeps access-loss tombstones across remounts and transient failures", async () => {
  const cache = new Map<string, State>();
  const load = jest
    .fn<Promise<string>, []>()
    .mockResolvedValueOnce("private bytes")
    .mockRejectedValueOnce(new FetchError("Forbidden", 403, null))
    .mockRejectedValueOnce(new FetchError("Offline", 503, null));
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <SWRConfig value={{ provider: () => cache, shouldRetryOnError: false }}>
      {children}
    </SWRConfig>
  );
  const first = renderHook(
    ({ refreshKey }) =>
      useFilePreview("remount-access", load, {
        revision: "v1",
        refreshKey,
      }),
    { wrapper, initialProps: { refreshKey: 0 } }
  );
  await waitFor(() => expect(first.result.current.data).toBe("private bytes"));
  first.rerender({ refreshKey: 1 });
  await waitFor(() =>
    expect(first.result.current.error?.message).toBe("Forbidden")
  );
  first.unmount();
  const second = renderHook(
    () =>
      useFilePreview("remount-access", load, { revision: "v1", refreshKey: 1 }),
    { wrapper }
  );
  expect(second.result.current.data).toBeUndefined();
  await waitFor(() =>
    expect(second.result.current.error?.message).toBe("Offline")
  );
  expect(second.result.current.data).toBeUndefined();
  expect(cache.size).toBe(1);
});

it("does not let a late access failure purge a newer successful revision", async () => {
  const old = deferred<string>();
  const load = jest
    .fn<Promise<string>, []>()
    .mockReturnValueOnce(old.promise)
    .mockResolvedValueOnce("new bytes");
  const { result, rerender } = renderHook(
    ({ revision }) => useFilePreview("late-access", load, { revision }),
    {
      initialProps: { revision: "old" },
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
      ),
    }
  );
  rerender({ revision: "new" });
  await waitFor(() => expect(result.current.data).toBe("new bytes"));
  await act(async () => old.reject(new FetchError("Forbidden", 403, null)));
  expect(result.current.data).toBe("new bytes");
  expect(result.current.error).toBeUndefined();
});

it("does not mutate loader errors when associating failures with requests", async () => {
  const failure = Object.freeze(new Error("Unavailable"));
  const load = jest.fn<Promise<string>, []>().mockRejectedValue(failure);
  const { result, rerender } = renderHook(
    ({ revision }) => useFilePreview("immutable-error", load, { revision }),
    {
      initialProps: { revision: "first" },
      wrapper: ({ children }) => (
        <SWRConfig
          value={{ provider: () => new Map(), shouldRetryOnError: false }}
        >
          {children}
        </SWRConfig>
      ),
    }
  );
  await waitFor(() => expect(result.current.error).toBe(failure));
  rerender({ revision: "second" });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(result.current.error).toBe(failure));
});

// Workspace listing invalidation.
it.each([401, 403, 404])(
  "purges workspace data and persisted fallback after terminal error (%s)",
  async (status) => {
    const load = jest
      .fn<Promise<string>, [AbortSignal]>()
      .mockResolvedValueOnce("private listing")
      .mockRejectedValueOnce(new FetchError("Unavailable", status, null))
      .mockRejectedValueOnce(new FetchError("Offline", 503, null))
      .mockResolvedValueOnce("authorized listing");
    const { result, rerender } = renderHook(
      ({ refreshGeneration }) =>
        useWorkspaceListing(`workspace-${status}`, load, {
          isActive: true,
          refreshGeneration,
          fallbackData: "persisted private listing",
        }),
      {
        initialProps: { refreshGeneration: 0 },
        wrapper: ({ children }) => (
          <SWRConfig value={{ provider: () => new Map() }}>
            {children}
          </SWRConfig>
        ),
      }
    );
    await waitFor(() => expect(result.current.data).toBe("private listing"));
    rerender({ refreshGeneration: 1 });
    await waitFor(() =>
      expect(result.current.error?.message).toBe("Unavailable")
    );
    expect(result.current.data).toBeUndefined();
    rerender({ refreshGeneration: 2 });
    await waitFor(() => expect(result.current.error?.message).toBe("Offline"));
    expect(result.current.data).toBeUndefined();
    rerender({ refreshGeneration: 3 });
    await waitFor(() => expect(result.current.data).toBe("authorized listing"));
  }
);

it("retains a terminal listing result across remounts without restoring fallback rows", async () => {
  const cache = new Map<string, State>();
  const denied = new FetchError("Denied", 403, null);
  const load = jest
    .fn<Promise<string>, [AbortSignal]>()
    .mockRejectedValue(denied);
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>
  );
  const first = renderHook(
    () =>
      useWorkspaceListing("denied-listing", load, {
        isActive: true,
        refreshGeneration: 0,
        fallbackData: "stored rows",
      }),
    { wrapper }
  );
  await waitFor(() => expect(first.result.current.error).toBe(denied));
  expect(first.result.current.data).toBeUndefined();
  first.unmount();
  const second = renderHook(
    () =>
      useWorkspaceListing("denied-listing", load, {
        isActive: false,
        refreshGeneration: 0,
        fallbackData: "stored rows",
      }),
    { wrapper }
  );
  expect(second.result.current.data).toBeUndefined();
  expect(second.result.current.error).toBe(denied);
  expect(load).toHaveBeenCalledTimes(1);
});

// Listener updates do not complete pending work.
it("keeps a pending preview marked refreshing when its callback changes", async () => {
  const pending = deferred<Blob>();
  const load = jest.fn(() => pending.promise);
  const first = jest.fn();
  const second = jest.fn();
  const { rerender, unmount } = renderHook(
    ({ listener }) =>
      useFilePreview("callback-preview", load, {
        revision: "v1",
        onRefreshingChange: listener,
      }),
    { initialProps: { listener: first } }
  );
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  expect(first).toHaveBeenLastCalledWith(true);
  rerender({ listener: second });
  expect(first).not.toHaveBeenCalledWith(false);
  expect(second).toHaveBeenLastCalledWith(true);
  expect(second).not.toHaveBeenCalledWith(false);
  await act(async () => pending.resolve(new Blob(["done"])));
  await waitFor(() => expect(second).toHaveBeenLastCalledWith(false));
  unmount();
  expect(first).not.toHaveBeenCalledWith(false);
});

// React development replay must not duplicate expensive preview conversion requests.
it("coalesces StrictMode replay while still superseding a pending preview revision", async () => {
  const old = deferred<Blob>();
  const current = deferred<Blob>();
  const load = jest
    .fn<Promise<Blob>, []>()
    .mockReturnValueOnce(old.promise)
    .mockReturnValueOnce(current.promise);
  const { rerender, result } = renderHook(
    ({ revision }) => useFilePreview("strict-preview", load, { revision }),
    {
      initialProps: { revision: "old" },
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => new Map() }}>
          <StrictMode>{children}</StrictMode>
        </SWRConfig>
      ),
    }
  );
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  rerender({ revision: "current" });
  await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  const accepted = new Blob(["current"]);
  await act(async () => current.resolve(accepted));
  expect(result.current.data).toBe(accepted);
  await act(async () => old.resolve(new Blob(["old"])));
  expect(result.current.data).toBe(accepted);
});

it("reads a webapp once for an initial nonzero generation and gates authenticated ownership", async () => {
  const load = jest.mocked(fetchWebappInfo);
  const first = deferred<Awaited<ReturnType<typeof fetchWebappInfo>>>();
  load.mockReset().mockReturnValueOnce(first.promise).mockResolvedValue({
    has_webapp: false,
    webapp_url: null,
    status: "active",
    ready: false,
    sharing_scope: "private",
  });
  mockPreviewUserId = "test-user";
  const { result, rerender } = renderHook(
    ({ revision }) =>
      useOutputWebapps({
        session: {
          sandbox: {
            id: "sandbox",
            status: "running",
            container_id: null,
            created_at: "2026-10-09T00:00:00Z",
            last_heartbeat: null,
          },
          status: "idle",
          webappNeedsRefresh: revision,
        },
        sessionId: "webapp-session",
        isOpen: true,
        hasBrowser: true,
        activeBrowser: false,
        appName: "local",
      }),
    {
      initialProps: { revision: 7 },
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => new Map() }}>
          <StrictMode key={mockPreviewUserId}>{children}</StrictMode>
        </SWRConfig>
      ),
    }
  );
  try {
    await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
    await act(async () =>
      first.resolve({
        has_webapp: true,
        webapp_url: "/first-user-app",
        status: "active",
        ready: true,
        sharing_scope: "private",
      })
    );
    expect(result.current.apps[0]?.url).toBe("/first-user-app");
    mockPreviewUserId = undefined;
    rerender({ revision: 7 });
    expect(result.current.canQuery).toBe(false);
    expect(result.current.apps).toEqual([]);
    expect(load).toHaveBeenCalledTimes(1);
    mockPreviewUserId = "other-user";
    rerender({ revision: 7 });
    expect(result.current.apps).toEqual([]);
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    rerender({ revision: 8 });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
  } finally {
    mockPreviewUserId = "test-user";
  }
});

it("does not retry a superseded preview after its new revision succeeds", async () => {
  jest.useFakeTimers();
  const accepted = new Blob(["current"]);
  const load = jest
    .fn<Promise<Blob>, []>()
    .mockRejectedValueOnce(new FetchError("temporary", 503, null))
    .mockResolvedValue(accepted);
  try {
    const { rerender, result } = renderHook(
      ({ revision }) => useFilePreview("obsolete-retry", load, { revision }),
      {
        initialProps: { revision: "old" },
        wrapper: ({ children }) => (
          <SWRConfig
            value={{ provider: () => new Map(), shouldRetryOnError: true }}
          >
            {children}
          </SWRConfig>
        ),
      }
    );
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeDefined();
    rerender({ revision: "current" });
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.data).toBe(accepted);
    await act(async () => jest.advanceTimersByTime(4000));
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.data).toBe(accepted);
  } finally {
    jest.useRealTimers();
  }
});

it("skips the old scheduled retry after same-revision activation recovery", async () => {
  jest.useFakeTimers();
  const obsolete = deferred<string>();
  const load = jest
    .fn<Promise<string>, []>()
    .mockRejectedValueOnce(new FetchError("temporary", 503, null))
    .mockResolvedValueOnce("recovered")
    .mockReturnValue(obsolete.promise);
  try {
    const { rerender, result } = renderHook(
      ({ isActive }) =>
        useFilePreview("recovered-retry", load, {
          revision: "known",
          isActive,
        }),
      {
        initialProps: { isActive: true },
        wrapper: ({ children }) => (
          <SWRConfig
            value={{ provider: () => new Map(), shouldRetryOnError: true }}
          >
            {children}
          </SWRConfig>
        ),
      }
    );
    await act(async () => {});
    expect(result.current.error).toBeDefined();
    rerender({ isActive: false });
    rerender({ isActive: true });
    await act(async () => {});
    expect(result.current.data).toBe("recovered");
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => jest.advanceTimersByTime(4000));
    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBe("recovered");
    expect(load).toHaveBeenCalledTimes(2);
  } finally {
    jest.useRealTimers();
  }
});

// Preview lifetime and rendering.
it("does not retry a preview after its viewer unmounts", async () => {
  jest.useFakeTimers();
  const load = jest
    .fn()
    .mockRejectedValue(new FetchError("temporary", 503, null));
  try {
    const { unmount, result } = renderHook(
      () => useFilePreview("retired-preview", load),
      {
        wrapper: ({ children }) => (
          <SWRConfig
            value={{ provider: () => new Map(), shouldRetryOnError: true }}
          >
            {children}
          </SWRConfig>
        ),
      }
    );
    await act(async () => {});
    expect(result.current.error).toBeDefined();
    expect(load).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => jest.advanceTimersByTime(4000));
    expect(load).toHaveBeenCalledTimes(1);
  } finally {
    jest.useRealTimers();
  }
});
