import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ActionsMenu } from "@/components/chat/ActionsMenu";
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
  const value: ComposerTools = makeComposerTools({
    actionTools: [searchTool, imageTool],
    ...overrides,
  });
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

  it("offers the source drill-in only on the row that owns it", () => {
    renderMenu({ sourceToolId: 1, sourceOptions: ["notion"] });
    fireEvent.press(screen.getByLabelText("Manage Actions"));

    expect(screen.getAllByLabelText("Configure Sources")).toHaveLength(1);
  });

  it("keeps the drill-in hidden while the agent has no sources to choose between", () => {
    renderMenu({ sourceToolId: 1, sourceOptions: [] });
    fireEvent.press(screen.getByLabelText("Manage Actions"));
    expect(screen.queryByLabelText("Configure Sources")).toBeNull();
  });

  it("swaps the body for the sources in place, and back", () => {
    renderMenu({
      sourceToolId: 1,
      sourceOptions: ["notion"],
      enabledSourceCount: 1,
      isSourceEnabled: () => true,
    });
    fireEvent.press(screen.getByLabelText("Manage Actions"));
    fireEvent.press(screen.getByLabelText("Configure Sources"));

    expect(screen.getByText("Sources")).toBeTruthy();
    expect(screen.getByText("Notion")).toBeTruthy();
    expect(screen.queryByText("Generate Image")).toBeNull();

    fireEvent.press(screen.getByLabelText("Back"));
    expect(screen.getByText("Actions")).toBeTruthy();
    expect(screen.getByText("Generate Image")).toBeTruthy();
  });

  it("marks the forced row and counts its sources", () => {
    // The leaf takes these as props; only the menu can prove it derives them the right way round.
    renderMenu({
      forcedToolId: 1,
      sourceToolId: 1,
      sourceOptions: ["notion", "web", "jira"],
      enabledSourceCount: 2,
    });
    fireEvent.press(screen.getByLabelText("Manage Actions"));

    expect(screen.getByText("2 of 3")).toBeTruthy();
  });

  it("closes instead of drilling in when the forced search row is tapped", () => {
    const value = renderMenu({
      forcedToolId: 1,
      sourceToolId: 1,
      sourceOptions: ["notion"],
      enabledSourceCount: 1,
    });
    fireEvent.press(screen.getByLabelText("Manage Actions"));
    fireEvent.press(screen.getByText("Search"));

    expect(value.toggleForcedTool).toHaveBeenCalledWith(1);
    expect(screen.queryByText("Notion")).toBeNull();
  });

  it("reopens on the tool list after the sub-view was left open", () => {
    renderMenu({
      sourceToolId: 1,
      sourceOptions: ["notion"],
      enabledSourceCount: 1,
      isSourceEnabled: () => true,
    });
    fireEvent.press(screen.getByLabelText("Manage Actions"));
    fireEvent.press(screen.getByLabelText("Configure Sources"));
    fireEvent.press(screen.getByLabelText("Close"));

    fireEvent.press(screen.getByLabelText("Manage Actions"));
    expect(screen.getByText("Actions")).toBeTruthy();
  });
});
