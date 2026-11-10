import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig, useSWRConfig } from "swr";
import { useUserGroupSkills } from "@/lib/groupSkills/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { deferred } from "@tests/setup/test-utils";

const key = SWR_KEYS.userGroupSkills(7);
const available = { marketplaces: [], skills: [] };

afterEach(() => jest.restoreAllMocks());

it.each([false, true])(
  "does not publish an older PUT over a denial (group changed: %s)",
  async (changeGroup) => {
    const pending = deferred<Response>();
    let readStatus = 200;
    jest.spyOn(global, "fetch").mockImplementation(async (_url, init) => {
      if (init?.method === "PUT") return pending.promise;
      return new Response(JSON.stringify(available), { status: readStatus });
    });
    const cache = new Map();
    function wrapper({ children }: { children: React.ReactNode }) {
      return (
        <SWRConfig
          value={{
            provider: () => cache,
            dedupingInterval: 0,
            shouldRetryOnError: false,
          }}
        >
          {children}
        </SWRConfig>
      );
    }
    const view = renderHook(
      ({ groupId }) => ({
        ...useUserGroupSkills(groupId),
        mutate: useSWRConfig().mutate,
      }),
      { wrapper, initialProps: { groupId: 7 } }
    );
    await waitFor(() => expect(view.result.current.data).toEqual(available));
    const saving = view.result.current.setPolicy(
      { kind: "skill", id: "skill" },
      "DEFAULT"
    );
    readStatus = 403;
    if (changeGroup) view.rerender({ groupId: 8 });
    else
      await act(async () => {
        await view.result.current.mutate(key);
      });
    await waitFor(() =>
      expect(view.result.current.error).toMatchObject({ status: 403 })
    );
    expect(view.result.current.data).toBeUndefined();
    readStatus = 503;
    await act(async () => {
      pending.resolve(new Response(JSON.stringify(available)));
      await saving.catch(() => undefined);
    });
    expect(view.result.current.data).toBeUndefined();
    view.unmount();
    const remount = renderHook(() => useUserGroupSkills(changeGroup ? 8 : 7), {
      wrapper,
    });
    await waitFor(() =>
      expect(remount.result.current.error).toMatchObject({ status: 503 })
    );
    expect(remount.result.current.data).toBeUndefined();
  }
);

it.each([401, 402, 403, 404])(
  "keeps a %s denial across errors and remounts until an authorized response",
  async (status) => {
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(new Response(JSON.stringify(available)));
    const cache = new Map();
    function wrapper({ children }: { children: React.ReactNode }) {
      return (
        <SWRConfig
          value={{
            provider: () => cache,
            dedupingInterval: 0,
            shouldRetryOnError: false,
          }}
        >
          {children}
        </SWRConfig>
      );
    }
    function useRead() {
      return { ...useUserGroupSkills(7), mutate: useSWRConfig().mutate };
    }
    const first = renderHook(useRead, { wrapper });
    await waitFor(() => expect(first.result.current.data).toEqual(available));
    fetchSpy.mockImplementation(async () => new Response("{}", { status }));
    await act(async () => {
      await first.result.current.mutate(key);
    });
    expect(first.result.current.data).toBeUndefined();
    expect(first.result.current.error).toMatchObject({ status });
    fetchSpy.mockImplementation(
      async () => new Response("{}", { status: 500 })
    );
    await act(async () => {
      await first.result.current.mutate(key).catch(() => undefined);
    });
    expect(first.result.current.data).toBeUndefined();
    first.unmount();
    const second = renderHook(useRead, { wrapper });
    await waitFor(() =>
      expect(second.result.current.error).toMatchObject({ status: 500 })
    );
    expect(second.result.current.data).toBeUndefined();
    fetchSpy.mockImplementation(
      async () => new Response(JSON.stringify(available))
    );
    await act(async () => {
      await second.result.current.mutate(key);
    });
    expect(second.result.current.data).toEqual(available);
    expect(second.result.current.error).toBeUndefined();
    second.unmount();
  }
);

it("retains authorized data through a transient failure", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify(available)));
  const cache = new Map();
  function wrapper({ children }: { children: React.ReactNode }) {
    return (
      <SWRConfig
        value={{
          provider: () => cache,
          dedupingInterval: 0,
          shouldRetryOnError: false,
        }}
      >
        {children}
      </SWRConfig>
    );
  }
  const { result } = renderHook(
    () => ({
      ...useUserGroupSkills(7),
      mutate: useSWRConfig().mutate,
    }),
    { wrapper }
  );
  await waitFor(() => expect(result.current.data).toEqual(available));
  fetchSpy.mockImplementation(async () => new Response("{}", { status: 503 }));
  await act(async () => {
    await result.current.mutate(key).catch(() => undefined);
  });
  expect(result.current.data).toEqual(available);
  expect(result.current.error).toMatchObject({ status: 503 });
});
