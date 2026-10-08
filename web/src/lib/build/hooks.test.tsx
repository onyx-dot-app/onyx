import { act, deferred, renderHook, waitFor } from "@tests/setup/test-utils";
import { SWRConfig, type State } from "swr";
import { useFilePreview } from "@/lib/build/hooks";

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
