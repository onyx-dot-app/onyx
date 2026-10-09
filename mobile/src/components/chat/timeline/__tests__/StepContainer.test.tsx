import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";
import { View } from "react-native";

import { StepContainer } from "@/components/chat/timeline/StepContainer";
import { Text } from "@/components/ui/text";
import SvgCircle from "@/icons/circle";
import SvgXOctagon from "@/icons/x-octagon";

// Button navigates via expo-router's `router`; stub it so the import resolves under jest.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

function Body() {
  return (
    <Text font="main-ui-body" color="text-05">
      step body
    </Text>
  );
}

describe("StepContainer", () => {
  it("renders the header status, body, and rail node icon (no error octagon)", () => {
    render(
      <StepContainer stepIcon={SvgCircle} header="Thinking">
        <Body />
      </StepContainer>,
    );
    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("step body")).toBeTruthy();
    expect(screen.UNSAFE_queryByType(SvgCircle)).toBeTruthy();
    expect(screen.UNSAFE_queryByType(SvgXOctagon)).toBeNull();
  });

  it("shows the collapse control only when collapsible + supportsCollapsible + onToggle", () => {
    const onToggle = jest.fn();
    render(
      <StepContainer
        header="Thinking"
        supportsCollapsible
        isExpanded
        onToggle={onToggle}
      >
        <Body />
      </StepContainer>,
    );
    const toggle = screen.getByLabelText("Collapse");
    fireEvent.press(toggle);
    expect(onToggle).toHaveBeenCalledTimes(1);
    // collapse control shown → the error-octagon branch isn't taken
    expect(screen.UNSAFE_queryByType(SvgXOctagon)).toBeNull();
  });

  it("hides the collapse control when the renderer does not support collapsing", () => {
    render(
      <StepContainer header="Done" onToggle={jest.fn()}>
        <Body />
      </StepContainer>,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("labels the toggle 'Expand' when collapsed", () => {
    render(
      <StepContainer
        header="Thinking"
        supportsCollapsible
        isExpanded={false}
        onToggle={jest.fn()}
      >
        <Body />
      </StepContainer>,
    );
    expect(screen.getByLabelText("Expand")).toBeTruthy();
  });

  it("renders a labelled toggle button when buttonTitle is set", () => {
    render(
      <StepContainer
        header="Sources"
        supportsCollapsible
        isExpanded
        onToggle={jest.fn()}
        buttonTitle="Show 3"
      >
        <Body />
      </StepContainer>,
    );
    expect(screen.getByText("Show 3")).toBeTruthy();
  });

  it("shows the error octagon on an error surface with no collapse control", () => {
    render(
      <StepContainer header="Failed" surfaceBackground="error">
        <Body />
      </StepContainer>,
    );
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.UNSAFE_queryByType(SvgXOctagon)).toBeTruthy();
  });

  it("omits the header and rail icon when hideHeader is set", () => {
    render(
      <StepContainer stepIcon={SvgCircle} header="Thinking" hideHeader>
        <Body />
      </StepContainer>,
    );
    expect(screen.queryByText("Thinking")).toBeNull();
    expect(screen.getByText("step body")).toBeTruthy();
    // showIcon = !hideHeader && Boolean(stepIcon) → false, so the rail icon drops
    expect(screen.UNSAFE_queryByType(SvgCircle)).toBeNull();
  });

  it("drops the rail column entirely when withRail is false", () => {
    render(
      <StepContainer stepIcon={SvgCircle} header="Nested" withRail={false}>
        <Body />
      </StepContainer>,
    );
    // no rail → the node icon (rail-only) isn't rendered
    expect(screen.UNSAFE_queryByType(SvgCircle)).toBeNull();
    expect(screen.getByText("Nested")).toBeTruthy();
    expect(screen.getByText("step body")).toBeTruthy();
  });

  it("renders a ReactElement header as-is (does not coerce it through Text)", () => {
    // A ReactElement header renders directly; wrapping a View in RN Text would throw, so a clean
    // render proves the element branch runs.
    render(
      <StepContainer
        header={
          <View testID="custom-header">
            <Text font="main-ui-muted" color="text-04">
              custom-status
            </Text>
          </View>
        }
      >
        <Body />
      </StepContainer>,
    );
    expect(screen.getByTestId("custom-header")).toBeTruthy();
    expect(screen.getByText("custom-status")).toBeTruthy();
  });
});
