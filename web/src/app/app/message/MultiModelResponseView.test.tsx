import { act, fireEvent, render, screen } from "@tests/setup/test-utils";
import MultiModelResponseView from "@/app/app/message/MultiModelResponseView";
import type { MultiModelPanelProps } from "@/app/app/message/MultiModelPanel";
import type { MultiModelResponse } from "@/app/app/message/types";
import type { FullChatState } from "@/app/app/message/messageComponents/types";
import useScreenSize from "@/hooks/useScreenSize";
import { useToolApprovalUi } from "@/lib/chat/toolApprovals";

jest.mock("@/hooks/useScreenSize", () => ({
  __esModule: true,
  default: jest.fn(),
}));
jest.mock("@/app/app/message/MultiModelPanel", () => ({
  __esModule: true,
  default: ({
    displayName,
    isHidden,
    carouselPrev,
    carouselNext,
    onToggleVisibility,
  }: MultiModelPanelProps) => (
    <div
      data-testid={`panel-${displayName}`}
      data-hidden={String(isHidden)}
      data-current={String(Boolean(carouselPrev || carouselNext))}
    >
      <button onClick={onToggleVisibility}>Hide {displayName}</button>
    </div>
  ),
}));

function response(modelIndex: number, approvalId?: string): MultiModelResponse {
  return {
    modelIndex,
    provider: "",
    modelName: `model-${modelIndex}`,
    displayName: `Model ${modelIndex}`,
    nodeId: modelIndex + 10,
    messageId: modelIndex + 10,
    packetCount: approvalId ? 1 : 0,
    packets: approvalId
      ? [
          {
            placement: { turn_index: 1, tab_index: 0, model_index: modelIndex },
            obj: {
              type: "tool_approval_request",
              approval_id: approvalId,
              tool_call_id: "call",
              tool_name: "mcp__3__github__create_issue",
              display_name: "Create issue",
              arguments: {},
            },
          },
        ]
      : [],
  };
}

function renderView(width: number, isSmallScreen: boolean) {
  jest.mocked(useScreenSize).mockReturnValue({
    width,
    height: 800,
    isMobile: isSmallScreen,
    isSmallScreen,
    isMediumScreen: false,
  });
  jest
    .spyOn(HTMLElement.prototype, "offsetWidth", "get")
    .mockReturnValue(width);
  render(
    <MultiModelResponseView
      responses={[response(0, "approval"), response(1), response(2)]}
      chatState={{} as FullChatState}
      llmManager={null}
    />
  );
}

// jsdom has no Web Animations API; the layout swap only fades.
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true,
    value: () => ({ cancel: () => {} }),
  });
});

afterEach(() => {
  jest.restoreAllMocks();
  useToolApprovalUi.setState({ nudge: null });
});

test("a nudged approval moves the carousel to the panel that holds it", () => {
  renderView(400, true);
  expect(screen.getByTestId("panel-Model 0").dataset.current).toBe("false");

  act(() => useToolApprovalUi.getState().nudgeApproval("approval"));

  expect(screen.getByTestId("panel-Model 0").dataset.current).toBe("true");
});

test("a nudged approval shows the hidden panel that holds it", () => {
  renderView(3000, false);
  fireEvent.click(screen.getByText("Hide Model 0"));
  expect(screen.getByTestId("panel-Model 0").dataset.hidden).toBe("true");

  act(() => useToolApprovalUi.getState().nudgeApproval("approval"));

  expect(screen.getByTestId("panel-Model 0").dataset.hidden).toBe("false");
});

test("a nudged approval whose reveal switches the row to the carousel shows its panel", () => {
  renderView(900, false);
  fireEvent.click(screen.getByText("Hide Model 0"));
  expect(screen.getByTestId("panel-Model 0").dataset.current).toBe("false");

  act(() => useToolApprovalUi.getState().nudgeApproval("approval"));

  expect(screen.getByTestId("panel-Model 0").dataset.hidden).toBe("false");
  expect(screen.getByTestId("panel-Model 0").dataset.current).toBe("true");
});
