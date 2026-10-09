import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { LineItemButton } from "@/components/ui/line-item-button";

jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

describe("LineItemButton", () => {
  it("renders title + description", () => {
    render(
      <LineItemButton
        sizePreset="main-ui"
        variant="section"
        title="Deploy"
        description="Last run 2h ago"
        onPress={jest.fn()}
      />,
    );
    expect(screen.getByText("Deploy")).toBeTruthy();
    expect(screen.getByText("Last run 2h ago")).toBeTruthy();
  });

  it("fires onPress when tapped", () => {
    const onPress = jest.fn();
    render(
      <LineItemButton
        sizePreset="main-ui"
        variant="section"
        title="Tap me"
        onPress={onPress}
      />,
    );
    fireEvent.press(screen.getByText("Tap me"));
    expect(onPress).toHaveBeenCalled();
  });
});
