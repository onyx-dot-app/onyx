import { describe, expect, it } from "@jest/globals";
import { renderHook } from "@testing-library/react-native";
import { StopReason } from "@/chat/streamingModels";
import { useTimelineHeader } from "@/hooks/timeline/useTimelineHeader";
import {
  makeItem,
  makeStep,
  makeTurn,
} from "@/hooks/timeline/__tests__/testHelpers";

describe("useTimelineHeader", () => {
  it("shows a waiting label before content arrives", () => {
    const { result } = renderHook(() => useTimelineHeader([]));
    expect(result.current.headerText).toBe("Thinking...");
    expect(result.current.hasPackets).toBe(false);
  });
  it("uses the current item's tool name and cancellation state", () => {
    const turn = makeTurn(0, [makeStep(0, 0, [makeItem("Jira")])]);
    const { result } = renderHook(() =>
      useTimelineHeader([turn], StopReason.USER_CANCELLED),
    );
    expect(result.current.headerText).toContain("Jira");
    expect(result.current.userStopped).toBe(true);
  });
});
