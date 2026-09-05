import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { SourceSwitchList } from "@/components/chat/SourceSwitchList";
import {
  ComposerToolsProvider,
  type ComposerTools,
} from "@/state/ComposerToolsProvider";
import { makeComposerTools } from "@/state/__tests__/fixtures";

jest.mock("@/state/storage");
jest.mock("@/api/settings", () => ({ useWorkspaceSettings: jest.fn() }));
jest.mock("@/hooks/useAgentPreferences", () => ({
  useAgentPreferences: jest.fn(),
}));

function renderList(overrides: Partial<ComposerTools> = {}) {
  const enabled = new Set(["notion"]);
  const value: ComposerTools = makeComposerTools({
    sourceOptions: ["notion", "web"],
    enabledSourceCount: enabled.size,
    isSourceEnabled: (source) => enabled.has(source),
    ...overrides,
  });
  render(
    <ComposerToolsProvider value={value}>
      <SourceSwitchList />
    </ComposerToolsProvider>,
  );
  return value;
}

describe("SourceSwitchList", () => {
  it("labels each source the way web does", () => {
    renderList();
    expect(screen.getByText("Notion")).toBeTruthy();
    expect(screen.getByText("Web")).toBeTruthy();
  });

  it("reflects which sources are on", () => {
    renderList();
    expect(
      screen.getByLabelText("Toggle Notion").props.accessibilityState,
    ).toEqual(expect.objectContaining({ checked: true }));
    expect(
      screen.getByLabelText("Toggle Web").props.accessibilityState,
    ).toEqual(expect.objectContaining({ checked: false }));
  });

  it("toggles from the switch", () => {
    const value = renderList();
    fireEvent.press(screen.getByLabelText("Toggle Web"));
    expect(value.toggleSource).toHaveBeenCalledWith("web");
  });

  it("toggles from anywhere on the row", () => {
    const value = renderList();
    fireEvent.press(screen.getByText("Web"));
    expect(value.toggleSource).toHaveBeenCalledWith("web");
  });

  it("offers Disable All while anything is on", () => {
    const value = renderList();
    fireEvent.press(screen.getByText("Disable All"));
    expect(value.disableAllSources).toHaveBeenCalledTimes(1);
  });

  it("offers Enable All once everything is off", () => {
    const value = renderList({
      enabledSourceCount: 0,
      isSourceEnabled: () => false,
    });
    fireEvent.press(screen.getByText("Enable All"));
    expect(value.enableAllSources).toHaveBeenCalledTimes(1);
  });

  it("renders nothing but the bulk action when the agent has no sources", () => {
    renderList({ sourceOptions: [], enabledSourceCount: 0 });
    expect(screen.queryByText("Notion")).toBeNull();
  });
});
