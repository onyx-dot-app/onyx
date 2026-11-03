import { type ReactNode } from "react";
import { SWRConfig } from "swr";
import { act, renderHook, waitFor } from "@tests/setup/test-utils";
import useOpenApiTools from "@/hooks/useOpenApiTools";

function Provider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        provider: () => new Map(),
        dedupingInterval: 0,
        shouldRetryOnError: false,
      }}
    >
      {children}
    </SWRConfig>
  );
}

afterEach(() => jest.restoreAllMocks());

test("authoritative refresh rejects HTTP failures while retaining cached records and publishes a successful retry", async () => {
  let fail = false;
  let name = "Release API";
  jest.spyOn(global, "fetch").mockImplementation(async () =>
    fail
      ? new Response(JSON.stringify({ detail: "List unavailable" }), {
          status: 503,
        })
      : new Response(
          JSON.stringify([
            { id: 42, name, permissions: { authenticate: true } },
          ])
        )
  );
  const { result } = renderHook(
    () => ({
      first: useOpenApiTools(),
      second: useOpenApiTools(),
    }),
    { wrapper: Provider }
  );
  await waitFor(() =>
    expect(result.current.first.openApiTools?.[0]?.name).toBe("Release API")
  );
  fail = true;
  await act(async () => {
    const cached = await result.current.first.mutateOpenApiTools();
    expect(cached?.[0]?.name).toBe("Release API");
    await expect(result.current.first.refreshOpenApiTools()).rejects.toThrow(
      "An error occurred while fetching the data."
    );
  });
  expect(result.current.second.openApiTools?.[0]?.name).toBe("Release API");
  fail = false;
  name = "Deployment API";
  await act(async () => {
    const refreshed = await result.current.first.refreshOpenApiTools();
    expect(refreshed?.[0]?.name).toBe("Deployment API");
  });
  await waitFor(() =>
    expect(result.current.second.openApiTools?.[0]?.name).toBe("Deployment API")
  );
});
