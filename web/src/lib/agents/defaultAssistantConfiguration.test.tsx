import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ReactNode } from "react";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { usePermissionAuthority } from "@/lib/permissions/hooks";

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
