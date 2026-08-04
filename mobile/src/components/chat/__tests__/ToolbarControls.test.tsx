import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ToolbarControls } from "@/components/chat/ToolbarControls";
import {
  ComposerToolsProvider,
  type ComposerTools,
} from "@/state/ComposerToolsProvider";

// The provider module pulls in the settings API (→ MMKV, no native binary under jest); this suite
// only uses the context.
jest.mock("@/api/settings", () => ({ useWorkspaceSettings: jest.fn() }));

function renderControls(overrides: Partial<ComposerTools> = {}) {
  const value: ComposerTools = {
    showDeepResearch: true,
    deepResearchEnabled: false,
    toggleDeepResearch: jest.fn(),
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
      <ToolbarControls />
    </ComposerToolsProvider>,
  );
  return value;
}

describe("ToolbarControls", () => {
  it("renders nothing when deep research is gated off", () => {
    renderControls({ showDeepResearch: false });
    expect(screen.queryByLabelText("Deep Research")).toBeNull();
  });

  it("renders the pill icon-only and unselected while off", () => {
    renderControls();
    const pill = screen.getByLabelText("Deep Research");
    expect(pill.props.accessibilityState.selected).toBe(false);
    expect(screen.queryByText("Deep Research")).toBeNull();
  });

  it("shows the label and the selected state once enabled", () => {
    renderControls({ deepResearchEnabled: true });
    expect(screen.getByText("Deep Research")).toBeTruthy();
    expect(
      screen.getByLabelText("Deep Research").props.accessibilityState.selected,
    ).toBe(true);
  });

  it("toggles on press", () => {
    const value = renderControls();
    fireEvent.press(screen.getByLabelText("Deep Research"));
    expect(value.toggleDeepResearch).toHaveBeenCalledTimes(1);
  });
});
