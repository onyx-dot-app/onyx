import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch, type ApiFetchInit } from "@/api/client";
import type { MinimalAgent } from "@/chat/agents";
import {
  FILE_READER_TOOL_ID,
  SEARCH_TOOL_ID,
  type ToolSnapshot,
} from "@/chat/tools";
import { useComposerToolsState } from "@/state/ComposerToolsProvider";

// `mock`-prefixed so babel-jest allows the hoisted factory to close over it.
let mockDeepResearchAdminEnabled = true;

jest.mock("@/api/client");
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));
jest.mock("@/hooks/useToast", () => ({ toast: { error: jest.fn() } }));
jest.mock("@/api/settings", () => ({
  useWorkspaceSettings: () => ({
    settings: {
      disable_default_assistant: false,
      user_file_max_upload_size_mb: null,
      deep_research_enabled: mockDeepResearchAdminEnabled,
    },
  }),
}));

const apiFetchMock = apiFetch as unknown as Mock<
  (path: string, init?: ApiFetchInit) => Promise<unknown>
>;

const searchTool: ToolSnapshot = {
  id: 1,
  name: "SearchTool",
  display_name: "Search",
  description: "",
  in_code_tool_id: SEARCH_TOOL_ID,
  mcp_server_id: null,
  chat_selectable: true,
};

const imageTool: ToolSnapshot = {
  id: 2,
  name: "ImageTool",
  display_name: "Image",
  description: "",
  in_code_tool_id: null,
  mcp_server_id: null,
  chat_selectable: true,
};

// Hidden from the menu but still part of the agent, so it must survive into allowed_tool_ids.
const fileReaderTool: ToolSnapshot = {
  id: 3,
  name: "FileReaderTool",
  display_name: "File Reader",
  description: "",
  in_code_tool_id: FILE_READER_TOOL_ID,
  mcp_server_id: null,
  chat_selectable: true,
};

function agent(tools: ToolSnapshot[]): MinimalAgent {
  return {
    id: 0,
    name: "Agent",
    description: "",
    starter_messages: null,
    uploaded_image_id: null,
    icon_name: null,
    is_public: true,
    is_listed: true,
    is_featured: false,
    builtin_persona: true,
    display_priority: null,
    labels: [],
    tools,
    knowledge_sources: [],
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderTools(
  overrides: { agent?: MinimalAgent | null; isProjectWorkflow?: boolean } = {},
) {
  return renderHook(
    () =>
      useComposerToolsState({
        chatSessionId: null,
        agent:
          overrides.agent === undefined ? agent([searchTool]) : overrides.agent,
        isProjectWorkflow: overrides.isProjectWorkflow ?? false,
        projectId: null,
      }),
    { wrapper },
  );
}

describe("useComposerToolsState", () => {
  beforeEach(() => {
    mockDeepResearchAdminEnabled = true;
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({});
  });

  it("shows deep research when the admin allows it and the agent can search", () => {
    expect(renderTools().result.current.showDeepResearch).toBe(true);
  });

  it("hides deep research when the admin setting is off", () => {
    mockDeepResearchAdminEnabled = false;
    expect(renderTools().result.current.showDeepResearch).toBe(false);
  });

  it("hides deep research when the agent has no search tool", () => {
    expect(
      renderTools({ agent: agent([]) }).result.current.showDeepResearch,
    ).toBe(false);
  });

  it("hides deep research while the agent is unknown and the pill is off", () => {
    expect(renderTools({ agent: null }).result.current.showDeepResearch).toBe(
      false,
    );
  });

  it("holds the pill through the agent-unknown window after a send", () => {
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: agent([searchTool]),
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    act(() => result.current.toggleDeepResearch());

    // Re-gating here would withdraw the control the user just used and drop it from the request.
    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });
    expect(result.current.showDeepResearch).toBe(true);
    expect(result.current.resolveToolOptions().deepResearch).toBe(true);
  });

  it("hides deep research in a project workflow", () => {
    expect(
      renderTools({ isProjectWorkflow: true }).result.current.showDeepResearch,
    ).toBe(false);
  });

  it("sends the toggled flag and leaves the unset fields null", () => {
    const { result } = renderTools();
    expect(result.current.resolveToolOptions()).toEqual({
      deepResearch: false,
      allowedToolIds: null,
      forcedToolId: null,
      internalSearchFilters: null,
    });

    act(() => result.current.toggleDeepResearch());
    expect(result.current.resolveToolOptions().deepResearch).toBe(true);
  });

  it("never sends deep research while the control is hidden", () => {
    const { result } = renderTools({ isProjectWorkflow: true });
    act(() => result.current.toggleDeepResearch());
    expect(result.current.resolveToolOptions().deepResearch).toBe(false);
  });

  it("exposes only the menu-displayable tools as rows", () => {
    const { result } = renderTools({
      agent: agent([searchTool, fileReaderTool]),
    });
    expect(result.current.actionTools.map((tool) => tool.id)).toEqual([1]);
  });

  it("has no rows while the agent is unresolved", () => {
    expect(renderTools({ agent: null }).result.current.actionTools).toEqual([]);
  });

  it("sends the forced tool id once a row is forced", () => {
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    act(() => result.current.toggleForcedTool(2));
    expect(result.current.resolveToolOptions().forcedToolId).toBe(2);
  });

  it("refuses to send a forced id the agent doesn't expose", () => {
    const { result } = renderTools({ agent: agent([searchTool]) });
    act(() => result.current.toggleForcedTool(99));
    expect(result.current.resolveToolOptions().forcedToolId).toBeNull();
  });

  it("computes allowed ids from every agent tool, not just the visible rows", async () => {
    apiFetchMock.mockResolvedValue({ "0": { disabled_tool_ids: [2] } });
    const { result } = renderTools({
      agent: agent([searchTool, imageTool, fileReaderTool]),
    });

    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));
    // 3 is the hidden File Reader — dropping it here would strip it server-side.
    expect(result.current.resolveToolOptions().allowedToolIds).toEqual([1, 3]);
  });

  it("releases the force when the forced tool is disabled", async () => {
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    act(() => result.current.toggleForcedTool(2));
    expect(result.current.forcedToolId).toBe(2);

    await act(async () => {
      result.current.toggleToolEnabled(2);
    });
    expect(result.current.forcedToolId).toBeNull();
  });

  it("keeps the force when a different tool is disabled", async () => {
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    act(() => result.current.toggleForcedTool(2));

    await act(async () => {
      result.current.toggleToolEnabled(1);
    });
    expect(result.current.forcedToolId).toBe(2);
  });

  it("keeps the menu rows while the agent is momentarily unknown", async () => {
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: agent([searchTool, imageTool]),
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    expect(result.current.actionTools).toHaveLength(2);

    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });
    // The menu and the forced pill both key off this; zeroing it hides them mid-conversation.
    expect(result.current.actionTools).toHaveLength(2);
  });

  it("keeps the disabled set while the agent is momentarily unknown", async () => {
    apiFetchMock.mockResolvedValue({ "0": { disabled_tool_ids: [2] } });
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: agent([searchTool, imageTool]),
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));

    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });
    expect(result.current.disabledToolIds).toEqual([2]);
    expect(result.current.resolveToolOptions().allowedToolIds).toEqual([1]);
  });

  it("still sends the force and the allowlist while the agent is momentarily unknown", async () => {
    apiFetchMock.mockResolvedValue({ "0": { disabled_tool_ids: [2] } });
    const { result, rerender } = renderHook(
      (props: Parameters<typeof useComposerToolsState>[0]) =>
        useComposerToolsState(props),
      {
        wrapper,
        initialProps: {
          chatSessionId: null,
          agent: agent([searchTool, imageTool, fileReaderTool]),
          isProjectWorkflow: false,
          projectId: null,
        },
      },
    );
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));
    act(() => result.current.toggleForcedTool(1));

    // The send created the session, but it hasn't reached the sessions list yet.
    rerender({
      chatSessionId: "session-1",
      agent: null,
      isProjectWorkflow: false,
      projectId: null,
    });

    expect(result.current.resolveToolOptions().forcedToolId).toBe(1);
    expect(result.current.resolveToolOptions().allowedToolIds).toEqual([1, 3]);
  });

  it("never sends a forced id that is also disabled", async () => {
    apiFetchMock.mockResolvedValue({ "0": { disabled_tool_ids: [2] } });
    const { result } = renderTools({ agent: agent([searchTool, imageTool]) });
    await waitFor(() => expect(result.current.disabledToolIds).toEqual([2]));

    act(() => result.current.toggleForcedTool(2));
    expect(result.current.resolveToolOptions().forcedToolId).toBeNull();
  });
});
