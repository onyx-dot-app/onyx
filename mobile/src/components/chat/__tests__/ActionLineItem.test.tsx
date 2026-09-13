import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ActionLineItem } from "@/components/chat/ActionLineItem";
import { SEARCH_TOOL_ID, type ToolSnapshot } from "@/chat/tools";

const tool: ToolSnapshot = {
  id: 1,
  name: "internal_search",
  display_name: "Search",
  description: "",
  in_code_tool_id: SEARCH_TOOL_ID,
  mcp_server_id: null,
  chat_selectable: true,
};

function renderRow(
  overrides: Partial<React.ComponentProps<typeof ActionLineItem>> = {},
) {
  const props = {
    tool,
    isForced: false,
    isDisabled: false,
    isUnavailable: false,
    sourceCounts: null,
    onForceToggle: jest.fn(),
    onToggleEnabled: jest.fn(),
    onOpenSources: jest.fn(),
    onClose: jest.fn(),
    ...overrides,
  };
  const view = render(<ActionLineItem {...props} />);
  return { ...props, toJSON: view.toJSON };
}

describe("ActionLineItem", () => {
  it("labels the row with the tool's display name", () => {
    renderRow();
    expect(screen.getByText("Search")).toBeTruthy();
  });

  it("falls back to the raw name when there is no display name", () => {
    renderRow({ tool: { ...tool, display_name: "" } });
    expect(screen.getByText("internal_search")).toBeTruthy();
  });

  it("forces the tool and closes the menu on row press", () => {
    const props = renderRow();
    fireEvent.press(screen.getByText("Search"));

    expect(props.onForceToggle).toHaveBeenCalledTimes(1);
    expect(props.onClose).toHaveBeenCalledTimes(1);
    expect(props.onToggleEnabled).not.toHaveBeenCalled();
  });

  it("re-enables and forces in one gesture when the tool is switched off", () => {
    const props = renderRow({ isDisabled: true });
    fireEvent.press(screen.getByText("Search"));

    expect(props.onToggleEnabled).toHaveBeenCalledTimes(1);
    expect(props.onForceToggle).toHaveBeenCalledTimes(1);
  });

  it("renders a forced row differently from an unforced one", () => {
    const unforced = renderRow({ isForced: false }).toJSON();
    const forced = renderRow({ isForced: true }).toJSON();

    expect(JSON.stringify(forced)).not.toEqual(JSON.stringify(unforced));
  });

  it("offers Disable while the tool is on", () => {
    renderRow();
    expect(screen.getByLabelText("Disable")).toBeTruthy();
    expect(screen.queryByLabelText("Enable")).toBeNull();
  });

  it("offers Enable while the tool is off", () => {
    renderRow({ isDisabled: true });
    expect(screen.getByLabelText("Enable")).toBeTruthy();
  });

  it("only toggles enablement when the trailing control is pressed", () => {
    const props = renderRow();
    fireEvent.press(screen.getByLabelText("Disable"));

    expect(props.onToggleEnabled).toHaveBeenCalledTimes(1);
    expect(props.onForceToggle).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("offers no source drill-in on a row that doesn't own sources", () => {
    renderRow();
    expect(screen.queryByLabelText("Configure Sources")).toBeNull();
  });

  it("drills into the sources from the chevron without forcing anything", () => {
    const props = renderRow({ sourceCounts: { enabled: 2, total: 3 } });
    fireEvent.press(screen.getByLabelText("Configure Sources"));

    expect(props.onOpenSources).toHaveBeenCalledTimes(1);
    expect(props.onForceToggle).not.toHaveBeenCalled();
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("drills in rather than dismissing when the row pins search", () => {
    const props = renderRow({ sourceCounts: { enabled: 3, total: 3 } });
    fireEvent.press(screen.getByText("Search"));

    expect(props.onForceToggle).toHaveBeenCalledTimes(1);
    expect(props.onOpenSources).toHaveBeenCalledTimes(1);
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it("just closes when the row releases search", () => {
    const props = renderRow({
      isForced: true,
      sourceCounts: { enabled: 3, total: 3 },
    });
    fireEvent.press(screen.getByText("Search"));

    expect(props.onForceToggle).toHaveBeenCalledTimes(1);
    expect(props.onOpenSources).not.toHaveBeenCalled();
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("counts the sources only while search is pinned and narrowed", () => {
    renderRow({ isForced: true, sourceCounts: { enabled: 2, total: 3 } });
    expect(screen.getByText("2 of 3")).toBeTruthy();
  });

  it("says nothing about a count that carries no information", () => {
    renderRow({ isForced: true, sourceCounts: { enabled: 3, total: 3 } });
    expect(screen.queryByText("3 of 3")).toBeNull();

    renderRow({ isForced: false, sourceCounts: { enabled: 2, total: 3 } });
    expect(screen.queryByText("2 of 3")).toBeNull();
  });
});
