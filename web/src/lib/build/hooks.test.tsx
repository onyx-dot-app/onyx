import { StrictMode } from "react";
import { act, deferred, renderHook, waitFor } from "@tests/setup/test-utils";
import { SWRConfig, type State } from "swr";
import { useFilePreview } from "@/lib/build/hooks";
import { FetchError, skipRetryOnAuthError } from "@/lib/fetcher";

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
