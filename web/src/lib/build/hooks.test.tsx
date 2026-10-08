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
    ({ revision }) => useFilePreview("file", load, revision),
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
      () => useFilePreview("retry-file", load, "v1"),
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
    ({ revision }) => useFilePreview("failed-file", load, revision),
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
    ({ revision }) => useFilePreview("late-failure", load, revision),
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
