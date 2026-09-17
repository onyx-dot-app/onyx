import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ToolbarControls } from "@/components/chat/ToolbarControls";
import { SEARCH_TOOL_ID, type ToolSnapshot } from "@/chat/tools";
import {
  ComposerToolsProvider,
  type ComposerTools,
} from "@/state/ComposerToolsProvider";
import { makeComposerTools } from "@/state/__tests__/fixtures";

// These reach MMKV, which jest can't load; the suite only needs the context the provider supplies.
jest.mock("@/state/storage");
jest.mock("@/api/settings", () => ({ useWorkspaceSettings: jest.fn() }));
jest.mock("@/hooks/useAgentPreferences", () => ({
  useAgentPreferences: jest.fn(),
}));
// ActionsMenu mounts the sheet shell even while closed.
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

const searchTool: ToolSnapshot = {
  id: 1,
  name: "internal_search",
  display_name: "Search",
  description: "",
  in_code_tool_id: SEARCH_TOOL_ID,
  mcp_server_id: null,
  chat_selectable: true,
};

function renderControls(overrides: Partial<ComposerTools> = {}) {
  const value: ComposerTools = makeComposerTools({
    showDeepResearch: true,
    ...overrides,
  });
  render(
    <ComposerToolsProvider value={value}>
      <ToolbarControls />
    </ComposerToolsProvider>,
  );
  return value;
}

describe("ToolbarControls", () => {
  // Deep research now lives in the actions sheet, so ActionsMenu covers how it behaves.
  it("keeps deep research out of the toolbar", () => {
    renderControls();
    expect(screen.queryByLabelText("Deep Research")).toBeNull();
  });

  it("hides the actions trigger when there is neither a tool nor deep research", () => {
    renderControls({ actionTools: [], showDeepResearch: false });
    expect(screen.queryByLabelText("Manage Actions")).toBeNull();
  });

  it("keeps the actions trigger for a toolless agent that still offers deep research", () => {
    renderControls({ actionTools: [], showDeepResearch: true });
    expect(screen.getByLabelText("Manage Actions")).toBeTruthy();
  });

  it("shows the actions trigger once the agent has selectable tools", () => {
    renderControls({ actionTools: [searchTool] });
    expect(screen.getByLabelText("Manage Actions")).toBeTruthy();
  });

  it("shows no forced pill when nothing is forced", () => {
    renderControls({ actionTools: [searchTool] });
    expect(screen.queryByLabelText("Search (forced)")).toBeNull();
  });

  it("shows a labelled forced pill and releases the force on press", () => {
    const value = renderControls({
      actionTools: [searchTool],
      forcedToolId: 1,
    });
    const pill = screen.getByLabelText("Search (forced)");
    expect(pill.props.accessibilityState.selected).toBe(true);

    fireEvent.press(pill);
    expect(value.toggleForcedTool).toHaveBeenCalledWith(1);
  });

  it("ignores a forced id the current agent doesn't expose", () => {
    renderControls({ actionTools: [searchTool], forcedToolId: 99 });
    expect(screen.queryByLabelText("Search (forced)")).toBeNull();
  });

  it("hides the pill for a forced tool that is switched off, matching what gets sent", () => {
    renderControls({
      actionTools: [searchTool],
      forcedToolId: 1,
      disabledToolIds: [1],
    });
    expect(screen.queryByLabelText("Search (forced)")).toBeNull();
  });
});
