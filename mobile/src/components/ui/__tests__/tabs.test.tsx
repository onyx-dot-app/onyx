import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import SvgGlobe from "@/icons/globe";
import SvgLoader from "@/icons/loader";
import SvgSearch from "@/icons/search";

// Button navigates via expo-router's `router`; stub it so the import resolves under jest.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

function renderTabs(props: {
  value: string;
  onValueChange: (value: string) => void;
  loading?: boolean;
  rightChildren?: React.ReactNode;
}) {
  return render(
    <Tabs value={props.value} onValueChange={props.onValueChange}>
      <Tabs.List rightChildren={props.rightChildren}>
        <Tabs.Trigger value="a" icon={SvgSearch} isLoading={props.loading}>
          Internal Search
        </Tabs.Trigger>
        <Tabs.Trigger value="b" icon={SvgGlobe}>
          Web Search
        </Tabs.Trigger>
      </Tabs.List>
    </Tabs>,
  );
}

describe("Tabs", () => {
  it("renders a trigger per tab with its icon", () => {
    renderTabs({ value: "a", onValueChange: jest.fn() });
    expect(screen.getByText("Internal Search")).toBeTruthy();
    expect(screen.getByText("Web Search")).toBeTruthy();
    expect(screen.UNSAFE_queryByType(SvgSearch)).toBeTruthy();
    expect(screen.UNSAFE_queryByType(SvgGlobe)).toBeTruthy();
  });

  it("marks only the active trigger as selected", () => {
    renderTabs({ value: "b", onValueChange: jest.fn() });
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]?.props.accessibilityState.selected).toBe(false);
    expect(tabs[1]?.props.accessibilityState.selected).toBe(true);
  });

  it("reports the pressed tab's value", () => {
    const onValueChange = jest.fn();
    renderTabs({ value: "a", onValueChange });
    fireEvent.press(screen.getByText("Web Search"));
    expect(onValueChange).toHaveBeenCalledWith("b");
  });

  it("renders the rightChildren slot outside the tab strip", () => {
    renderTabs({
      value: "a",
      onValueChange: jest.fn(),
      rightChildren: <Button prominence="tertiary">Fold</Button>,
    });
    expect(screen.getByText("Fold")).toBeTruthy();
  });

  it("shows a spinner only while a tab is still running", () => {
    // The Spinner wraps the loader glyph, so its presence is the loading signal.
    renderTabs({ value: "a", onValueChange: jest.fn(), loading: true });
    expect(screen.UNSAFE_queryByType(SvgLoader)).toBeTruthy();

    screen.unmount();
    renderTabs({ value: "a", onValueChange: jest.fn(), loading: false });
    expect(screen.UNSAFE_queryByType(SvgLoader)).toBeNull();
  });
});
