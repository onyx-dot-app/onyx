import { act, render, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ReactNode } from "react";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { deferred } from "@tests/setup/test-utils";

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: jest.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig
      value={{
        provider: () => new Map(),
        shouldRetryOnError: false,
        dedupingInterval: 0,
      }}
    >
      {children}
    </SWRConfig>
  );
}

beforeEach(() => {
  jest
    .mocked(usePermissionAuthority)
    .mockReturnValue({ isGlobalHolder: true, isScopedManager: false });
});
afterEach(() => jest.restoreAllMocks());

function configurationResponse(toolIds: number[]) {
  return new Response(
    JSON.stringify({
      tool_ids: toolIds,
      system_prompt: null,
      default_system_prompt: "",
    })
  );
}

test("concurrent surfaces preserve both changes to default Chat tools", async () => {
  let ids = [1, 2, 99];
  const patches: number[][] = [];
  const firstPatch = deferred<void>();
  jest.spyOn(global, "fetch").mockImplementation(async (_url, init) => {
    if (init?.method === "PATCH") {
      const { tool_ids: nextIds }: { tool_ids: number[] } = JSON.parse(
        String(init.body)
      );
      patches.push(nextIds);
      if (patches.length === 1) await firstPatch.promise;
      ids = nextIds;
    }
    return configurationResponse(ids);
  });
  const { result } = renderHook(
    () => ({
      first: useDefaultAssistantConfiguration(),
      second: useDefaultAssistantConfiguration(),
    }),
    { wrapper }
  );
  await waitFor(() =>
    expect(result.current.second.data?.tool_ids).toEqual([1, 2, 99])
  );

  let saves: Promise<void>[] = [];
  await act(async () => {
    saves = [
      result.current.first.updateTools([1], false),
      result.current.second.updateTools([2], false),
    ];
  });
  const startedBeforeRelease = patches.map((patch) => [...patch]);
  const pendingBeforeRelease = [
    result.current.first.isSaving,
    result.current.second.isSaving,
  ];
  await act(async () => {
    firstPatch.resolve();
    await Promise.all(saves);
  });

  expect(startedBeforeRelease).toEqual([[2, 99]]);
  expect(pendingBeforeRelease).toEqual([true, true]);
  expect(patches).toEqual([[2, 99], [99]]);
  expect(ids).toEqual([99]);
  expect(result.current.first.data?.tool_ids).toEqual([99]);
  expect(result.current.second.data?.tool_ids).toEqual([99]);
  expect(result.current.first.isSaving).toBe(false);
  expect(result.current.second.isSaving).toBe(false);
});

test("a rejected save rolls back before another surface saves", async () => {
  let ids = [1, 2, 99];
  const patches: number[][] = [];
  const firstPatch = deferred<Response>();
  jest.spyOn(global, "fetch").mockImplementation(async (_url, init) => {
    if (init?.method === "PATCH") {
      const { tool_ids: nextIds }: { tool_ids: number[] } = JSON.parse(
        String(init.body)
      );
      patches.push(nextIds);
      if (patches.length === 1) return firstPatch.promise;
      ids = nextIds;
    }
    return configurationResponse(ids);
  });
  const { result } = renderHook(
    () => ({
      first: useDefaultAssistantConfiguration(),
      second: useDefaultAssistantConfiguration(),
    }),
    { wrapper }
  );
  await waitFor(() =>
    expect(result.current.second.data?.tool_ids).toEqual([1, 2, 99])
  );

  let firstSave = Promise.resolve();
  let secondSave = Promise.resolve();
  await act(async () => {
    firstSave = result.current.first.updateTools([1], false);
    secondSave = result.current.second.updateTools([2], false);
  });
  const startedBeforeRelease = patches.map((patch) => [...patch]);
  const rejection = expect(firstSave).rejects.toThrow("Save failed");
  await act(async () => {
    firstPatch.resolve(
      new Response(JSON.stringify({ detail: "Save failed" }), { status: 500 })
    );
    await rejection;
    await secondSave;
  });

  expect(startedBeforeRelease).toEqual([[2, 99]]);
  expect(patches).toEqual([
    [2, 99],
    [1, 99],
  ]);
  expect(ids).toEqual([1, 99]);
  expect(result.current.first.data?.tool_ids).toEqual([1, 99]);
  expect(result.current.second.data?.tool_ids).toEqual([1, 99]);
  expect(result.current.first.isSaving).toBe(false);
  expect(result.current.second.isSaving).toBe(false);
});

test("separate SWR providers save without waiting for one another", async () => {
  const patches: number[][] = [];
  const firstPatch = deferred<void>();
  jest.spyOn(global, "fetch").mockImplementation(async (_url, init) => {
    if (init?.method !== "PATCH") return configurationResponse([1, 2, 99]);
    const { tool_ids: nextIds }: { tool_ids: number[] } = JSON.parse(
      String(init.body)
    );
    patches.push(nextIds);
    if (patches.length === 1) await firstPatch.promise;
    return configurationResponse(nextIds);
  });
  const first = renderHook(useDefaultAssistantConfiguration, { wrapper });
  const second = renderHook(useDefaultAssistantConfiguration, { wrapper });
  await waitFor(() => {
    expect(first.result.current.data?.tool_ids).toEqual([1, 2, 99]);
    expect(second.result.current.data?.tool_ids).toEqual([1, 2, 99]);
  });

  let firstSave = Promise.resolve();
  await act(async () => {
    firstSave = first.result.current.updateTools([1], false);
    await second.result.current.updateTools([2], false);
  });
  expect(patches).toEqual([
    [2, 99],
    [1, 99],
  ]);
  expect(first.result.current.isSaving).toBe(true);
  expect(second.result.current.isSaving).toBe(false);
  expect(second.result.current.data?.tool_ids).toEqual([1, 99]);
  await act(async () => {
    firstPatch.resolve();
    await firstSave;
  });
  expect(first.result.current.data?.tool_ids).toEqual([2, 99]);
  expect(second.result.current.data?.tool_ids).toEqual([1, 99]);
});

test("accepted saves finish after their caller unmounts", async () => {
  const consumers = new Map<
    "first" | "second",
    ReturnType<typeof useDefaultAssistantConfiguration>
  >();
  function Consumer({ name }: { name: "first" | "second" }) {
    consumers.set(name, useDefaultAssistantConfiguration());
    return null;
  }
  function Consumers({ showFirst }: { showFirst: boolean }) {
    return (
      <>
        {showFirst && <Consumer name="first" />}
        <Consumer name="second" />
      </>
    );
  }
  let ids = [1, 2, 99];
  const patches: number[][] = [];
  const firstPatch = deferred<void>();
  jest.spyOn(global, "fetch").mockImplementation(async (_url, init) => {
    if (init?.method === "PATCH") {
      const { tool_ids: nextIds }: { tool_ids: number[] } = JSON.parse(
        String(init.body)
      );
      patches.push(nextIds);
      if (patches.length === 1) await firstPatch.promise;
      ids = nextIds;
    }
    return configurationResponse(ids);
  });
  const view = render(<Consumers showFirst />, { wrapper });
  await waitFor(() => {
    expect(consumers.get("first")?.data?.tool_ids).toEqual([1, 2, 99]);
    expect(consumers.get("second")?.data?.tool_ids).toEqual([1, 2, 99]);
  });
  const first = consumers.get("first");
  const second = consumers.get("second");
  if (!first || !second)
    throw new Error("Default Chat consumers did not mount");

  let saves: Promise<void>[] = [];
  await act(async () => {
    saves = [first.updateTools([1], false), second.updateTools([2], false)];
  });
  view.rerender(<Consumers showFirst={false} />);
  await act(async () => {
    firstPatch.resolve();
    await Promise.all(saves);
  });
  expect(patches).toEqual([[2, 99], [99]]);
  expect(ids).toEqual([99]);
  expect(consumers.get("second")?.data?.tool_ids).toEqual([99]);
  expect(consumers.get("second")?.isSaving).toBe(false);
});

test("both surfaces share selections and preserve other tools", async () => {
  let ids = [1, 99];
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, init) => {
      if (init?.method === "PATCH")
        ids = JSON.parse(String(init.body)).tool_ids;
      return new Response(
        JSON.stringify({
          tool_ids: ids,
          system_prompt: null,
          default_system_prompt: "",
        })
      );
    });
  const { result } = renderHook(
    () => ({
      preferences: useDefaultAssistantConfiguration(),
      mcp: useDefaultAssistantConfiguration(),
    }),
    { wrapper }
  );
  await waitFor(() =>
    expect(result.current.mcp.data?.tool_ids).toEqual([1, 99])
  );
  await act(() => result.current.mcp.updateTools([1, 2], false));
  expect(result.current.preferences.data?.tool_ids).toEqual([99]);
  await act(() => result.current.preferences.updateTools([2], true));
  expect(result.current.mcp.data?.tool_ids).toEqual([99, 2]);
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/admin/default-assistant",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ tool_ids: [99, 2] }),
    })
  );
});

test("failed save restores selections for both surfaces", async () => {
  jest.spyOn(global, "fetch").mockImplementation(async (_url, init) =>
    init?.method === "PATCH"
      ? new Response(JSON.stringify({ detail: "Save failed" }), {
          status: 500,
        })
      : new Response(
          JSON.stringify({
            tool_ids: [1, 99],
            system_prompt: null,
            default_system_prompt: "",
          })
        )
  );
  const { result } = renderHook(
    () => ({
      preferences: useDefaultAssistantConfiguration(),
      mcp: useDefaultAssistantConfiguration(),
    }),
    { wrapper }
  );
  await waitFor(() => expect(result.current.mcp.data).toBeDefined());
  await act(async () => {
    await expect(result.current.mcp.updateTools([1], false)).rejects.toThrow(
      "Save failed"
    );
  });
  expect(result.current.preferences.data?.tool_ids).toEqual([1, 99]);
  expect(result.current.mcp.isSaving).toBe(false);
});

test("scoped managers do not fetch or change global default Chat settings", async () => {
  jest
    .mocked(usePermissionAuthority)
    .mockReturnValue({ isGlobalHolder: false, isScopedManager: true });
  const fetchSpy = jest.spyOn(global, "fetch");
  const { result } = renderHook(useDefaultAssistantConfiguration, { wrapper });
  await act(() => result.current.updateTools([1], true));
  expect(result.current.canEdit).toBe(false);
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("rapid toggles preserve each completed selection", async () => {
  let ids = [99];
  jest.spyOn(global, "fetch").mockImplementation(async (_url, init) => {
    if (init?.method === "PATCH") ids = JSON.parse(String(init.body)).tool_ids;
    return new Response(
      JSON.stringify({
        tool_ids: ids,
        system_prompt: null,
        default_system_prompt: "",
      })
    );
  });
  const { result } = renderHook(useDefaultAssistantConfiguration, { wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  await act(async () => {
    await Promise.all([
      result.current.updateTools([1], true),
      result.current.updateTools([2], true),
    ]);
  });
  expect(result.current.data?.tool_ids).toEqual([99, 1, 2]);
  expect(result.current.isSaving).toBe(false);
});
