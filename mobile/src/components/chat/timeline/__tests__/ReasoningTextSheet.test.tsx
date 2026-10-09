import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { ScrollView } from "react-native";

import { ReasoningTextSheet } from "@/components/chat/timeline/ReasoningTextSheet";
import { toast } from "@/hooks/useToast";

let mockMarkdownProps: { content: string; isStreaming: boolean } | null = null;
jest.mock("@/components/chat/StreamingMarkdown", () => ({
  StreamingMarkdown: (props: { content: string; isStreaming: boolean }) => {
    mockMarkdownProps = props;
    return null;
  },
}));

jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 34, left: 0, right: 0 }),
}));

// jest-expo reports a 750x1334 window, so screen-relative sizing is assertable.
const SCREEN_HEIGHT = 1334;

const mockSetString = jest.fn(async (_text: string) => true);
jest.mock("expo-clipboard", () => ({
  setStringAsync: (text: string) => mockSetString(text),
}));

const CONTENT = "# Planning\n\nthe body";

function renderSheet(onClose = jest.fn()) {
  return render(
    <ReasoningTextSheet visible onClose={onClose} content={CONTENT} />,
  );
}

describe("ReasoningTextSheet", () => {
  beforeEach(() => {
    mockMarkdownProps = null;
    mockSetString.mockClear();
  });

  // The copy toast holds a 4s dismissal timer that would otherwise outlive the run.
  afterEach(() => {
    toast.clearAll();
  });

  it("renders the full reasoning, heading included", () => {
    renderSheet();
    expect(mockMarkdownProps?.content).toBe(CONTENT);
    // The reader is never mid-stream; it always shows a settled snapshot.
    expect(mockMarkdownProps?.isStreaming).toBe(false);
  });

  it("titles the sheet and reports size and line count", () => {
    renderSheet();
    expect(screen.getByText("Full text")).toBeTruthy();
    expect(screen.getByText("20 Bytes")).toBeTruthy();
    // "# Planning" / "" / "the body"
    expect(screen.getByText("3 lines")).toBeTruthy();
  });

  // Reasoning is long-form, so the body takes most of the screen — unlike 9a's short Sources list.
  it("sizes the body to most of the screen, not a fixed 420px", () => {
    renderSheet();
    const body = screen.UNSAFE_getAllByType(ScrollView)[0]!;
    const maxHeight = (body.props.style as { maxHeight: number }).maxHeight;
    expect(maxHeight).toBe(Math.round(SCREEN_HEIGHT * 0.7));
    expect(maxHeight).toBeGreaterThan(420);
  });

  it("copies the full reasoning", async () => {
    renderSheet();
    await act(async () => {
      fireEvent.press(screen.getByText("Copy"));
    });
    expect(mockSetString).toHaveBeenCalledWith(CONTENT);
  });

  it("closes on the close control", () => {
    const onClose = jest.fn();
    renderSheet(onClose);
    fireEvent.press(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
