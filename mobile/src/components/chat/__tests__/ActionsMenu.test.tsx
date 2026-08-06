import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ActionsMenu } from "@/components/chat/ActionsMenu";
import { SEARCH_TOOL_ID, type ToolSnapshot } from "@/chat/tools";
import {
  ComposerToolsProvider,
  type ComposerTools,
} from "@/state/ComposerToolsProvider";

// The provider reaches MMKV via the settings/preferences APIs, which jest can't load; this suite
// only needs the context.
jest.mock("@/api/settings", () => ({ useWorkspaceSettings: jest.fn() }));
jest.mock("@/hooks/useAgentPreferences", () => ({
  useAgentPreferences: jest.fn(),
}));
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

const imageTool: ToolSnapshot = {
  id: 2,
  name: "generate_image",
  display_name: "Generate Image",
  description: "",
  in_code_tool_id: null,
  mcp_server_id: null,
  chat_selectable: true,
};

function renderMenu(overrides: Partial<ComposerTools> = {}) {
  const value: ComposerTools = {
    showDeepResearch: false,
    deepResearchEnabled: false,
    toggleDeepResearch: jest.fn(),
    actionTools: [searchTool, imageTool],
    forcedToolId: null,
    toggleForcedTool: jest.fn(),
    disabledToolIds: [],
    toggleToolEnabled: jest.fn(),
    notePendingSend: jest.fn(),
    resolveToolOptions: () => ({
      deepResearch: false,
      allowedToolIds: null,
      forcedToolId: null,
      internalSearchFilters: null,
    }),
    ...overrides,
  };
  render(
    <ComposerToolsProvider value={value}>
      <ActionsMenu />
    </ComposerToolsProvider>,
  );
  return value;
}

describe("ActionsMenu", () => {
  it("renders nothing when the agent exposes no selectable tools", () => {
    renderMenu({ actionTools: [] });
    expect(screen.queryByLabelText("Manage Actions")).toBeNull();
  });

  it("keeps the tool list closed until the trigger is pressed", () => {
    renderMenu();
    expect(screen.queryByText("Search")).toBeNull();
  });

  it("lists every tool once opened, in agent order", () => {
    renderMenu();
    fireEvent.press(screen.getByLabelText("Manage Actions"));

    // An ordered exact match, so a duplicated or reordered row fails here.
    const labels = screen
      .getAllByText(/^(Search|Generate Image)$/)
      .map((node) => node.props.children);
    expect(labels).toEqual(["Search", "Generate Image"]);
  });

  it("forces the tapped tool and closes", () => {
    const value = renderMenu();
    fireEvent.press(screen.getByLabelText("Manage Actions"));
    fireEvent.press(screen.getByText("Generate Image"));

    expect(value.toggleForcedTool).toHaveBeenCalledWith(2);
    expect(screen.queryByText("Generate Image")).toBeNull();
  });

  it("routes the trailing control to the enable/disable toggle", () => {
    const value = renderMenu({ disabledToolIds: [2] });
    fireEvent.press(screen.getByLabelText("Manage Actions"));

    // Search is on → "Disable"; Generate Image is off → "Enable".
    fireEvent.press(screen.getByLabelText("Enable"));
    expect(value.toggleToolEnabled).toHaveBeenCalledWith(2);
  });
});
