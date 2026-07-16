import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { SelectButton } from "@/components/ui/select-button";
import SvgHourglass from "@/icons/hourglass";

describe("SelectButton", () => {
  it("shows the label when not foldable", () => {
    render(
      <SelectButton icon={SvgHourglass} accessibilityLabel="Deep Research">
        Deep Research
      </SelectButton>,
    );
    expect(screen.getByText("Deep Research")).toBeTruthy();
  });

  it("hides the label when folded (icon-only)", () => {
    render(
      <SelectButton
        icon={SvgHourglass}
        foldable
        accessibilityLabel="Deep Research"
      >
        Deep Research
      </SelectButton>,
    );
    expect(screen.queryByText("Deep Research")).toBeNull();
  });

  it("fires onPress when tapped", () => {
    const onPress = jest.fn();
    render(
      <SelectButton
        icon={SvgHourglass}
        onPress={onPress}
        accessibilityLabel="Deep Research"
      />,
    );
    fireEvent.press(screen.getByLabelText("Deep Research"));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("does not fire onPress when disabled", () => {
    const onPress = jest.fn();
    render(
      <SelectButton
        icon={SvgHourglass}
        disabled
        onPress={onPress}
        accessibilityLabel="Deep Research"
      />,
    );
    fireEvent.press(screen.getByLabelText("Deep Research"));
    expect(onPress).not.toHaveBeenCalled();
  });
});
