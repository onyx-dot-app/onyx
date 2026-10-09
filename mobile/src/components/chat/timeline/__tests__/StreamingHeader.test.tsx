import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { act, render, screen } from "@testing-library/react-native";

import { StreamingHeader } from "@/components/chat/timeline/headers/StreamingHeader";

// Button navigates via expo-router's `router`; stub it so the import resolves under jest.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

const START = 1_700_000_000_000;

describe("StreamingHeader", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(START);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  function renderHeader(overrides = {}) {
    return render(
      <StreamingHeader
        headerText="Thinking"
        collapsible
        isExpanded={false}
        onToggle={jest.fn()}
        {...overrides}
      />,
    );
  }

  it("renders the activity label", () => {
    renderHeader();
    expect(screen.getByText("Thinking")).toBeTruthy();
  });

  it("hides the elapsed readout while collapsed", () => {
    renderHeader({ streamingStartTime: START });
    act(() => {
      jest.advanceTimersByTime(5_000);
    });
    expect(screen.queryByText("5s")).toBeNull();
  });

  it("counts up once expanded", () => {
    renderHeader({ isExpanded: true, streamingStartTime: START });
    // Modern fake timers advance Date.now() too, so this alone moves the clock 5s.
    act(() => {
      jest.advanceTimersByTime(5_000);
    });
    expect(screen.getByText("5s")).toBeTruthy();
  });

  it("freezes on the backend duration when one arrives", () => {
    renderHeader({
      isExpanded: true,
      streamingStartTime: START,
      toolProcessingDuration: 12,
    });
    act(() => {
      jest.advanceTimersByTime(30_000);
    });
    expect(screen.getByText("12s")).toBeTruthy();
    expect(screen.queryByText("30s")).toBeNull();
  });

  it("drops the toggle entirely when not collapsible", () => {
    renderHeader({ collapsible: false });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("uses buttonTitle in place of the elapsed readout", () => {
    renderHeader({
      isExpanded: true,
      streamingStartTime: START,
      buttonTitle: "Details",
    });
    expect(screen.getByText("Details")).toBeTruthy();
  });
});
