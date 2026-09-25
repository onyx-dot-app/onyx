import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { makePacket, makePlacedPacket } from "@/chat/__tests__/fixtures";
import { createInitialState, processPackets } from "@/chat/messageProcessor";
import { StopReason, type Packet } from "@/chat/streamingModels";
import {
  groupStepsByTurn,
  transformPacketGroups,
} from "@/chat/timeline/transformers";
import { AgentTimeline } from "@/components/chat/AgentTimeline";
import type { FullChatState } from "@/components/chat/renderers/timelineContract";

// StreamingMarkdown pulls a native markdown module; render its text so bodies stay assertable.
jest.mock("@/components/chat/StreamingMarkdown", () => {
  const { Text } = jest.requireActual<typeof import("@/components/ui/text")>(
    "@/components/ui/text",
  );
  return {
    StreamingMarkdown: ({ content }: { content: string }) => (
      <Text>{content}</Text>
    ),
  };
});

// Buttons navigate via expo-router's `router`; stub it so the import resolves under jest.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

// The avatar reaches MMKV through its bearer-image path, which has no native binary under jest.
// These tests pass `agent: null`, so it never renders anyway.
jest.mock("@/components/avatars/AgentAvatar", () => ({
  AgentAvatar: () => null,
}));

const chatState: FullChatState = { agent: null };

const reasoningStart = (turn = 0) =>
  makePacket({ type: "reasoning_start" }, turn);
const reasoningDelta = (reasoning: string, turn = 0) =>
  makePacket({ type: "reasoning_delta", reasoning }, turn);
const sectionEnd = (turn = 0) => makePacket({ type: "section_end" }, turn);
const overallStop = (stopReason?: StopReason) =>
  makePacket({ type: "stop", stop_reason: stopReason });

// Mirrors what MessageRow feeds the timeline.
function turnGroupsFor(packets: Packet[]) {
  const state = processPackets(createInitialState(1), packets);
  return {
    turnGroups: groupStepsByTurn(transformPacketGroups(state.toolGroups)),
    state,
  };
}

function renderTimeline(packets: Packet[], overrides = {}) {
  const { turnGroups, state } = turnGroupsFor(packets);
  const result = render(
    <AgentTimeline
      turnGroups={turnGroups}
      chatState={chatState}
      stopPacketSeen={state.stopPacketSeen}
      stopReason={state.stopReason}
      {...overrides}
    />,
  );
  return { ...result, turnGroups, state };
}

describe("AgentTimeline", () => {
  it("shows the shimmering EMPTY header before any packet arrives", () => {
    renderTimeline([]);
    expect(screen.getByText("Thinking...")).toBeTruthy();
  });

  it("streams a reasoning step under a live 'Thinking' header", () => {
    renderTimeline([reasoningStart(), reasoningDelta("Weighing the options")]);

    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.getByText("Weighing the options")).toBeTruthy();
  });

  it("collapses to 'Thought for Xs' with a step count once the answer arrives", () => {
    const { turnGroups } = turnGroupsFor([
      reasoningStart(),
      reasoningDelta("done thinking"),
      sectionEnd(),
      overallStop(),
    ]);

    render(
      <AgentTimeline
        turnGroups={turnGroups}
        chatState={chatState}
        stopPacketSeen
        hasDisplayContent
        processingDurationSeconds={4}
      />,
    );

    expect(screen.getByText("Thought for 4s")).toBeTruthy();
    expect(screen.getByText("1 step")).toBeTruthy();
    expect(screen.queryByText("done thinking")).toBeNull();
  });

  it("falls back to 'Thought for some time' with no backend duration", () => {
    const { turnGroups } = turnGroupsFor([
      reasoningStart(),
      sectionEnd(),
      overallStop(),
    ]);
    render(
      <AgentTimeline
        turnGroups={turnGroups}
        chatState={chatState}
        stopPacketSeen
        hasDisplayContent
      />,
    );
    expect(screen.getByText("Thought for some time")).toBeTruthy();
  });

  it("expands the step list when the completed header is tapped", () => {
    const { turnGroups } = turnGroupsFor([
      reasoningStart(),
      reasoningDelta("the hidden reasoning"),
      sectionEnd(),
      overallStop(),
    ]);
    render(
      <AgentTimeline
        turnGroups={turnGroups}
        chatState={chatState}
        stopPacketSeen
        hasDisplayContent
        processingDurationSeconds={2}
      />,
    );

    expect(screen.queryByText("the hidden reasoning")).toBeNull();
    fireEvent.press(screen.getByText("1 step"));
    expect(screen.getByText("the hidden reasoning")).toBeTruthy();
    expect(screen.getByText("Done")).toBeTruthy();
  });

  it("pluralizes the step count across turns", () => {
    const { turnGroups } = turnGroupsFor([
      reasoningStart(0),
      sectionEnd(0),
      reasoningStart(1),
      sectionEnd(1),
      overallStop(),
    ]);
    render(
      <AgentTimeline
        turnGroups={turnGroups}
        chatState={chatState}
        stopPacketSeen
        hasDisplayContent
        processingDurationSeconds={9}
      />,
    );
    expect(screen.getByText("2 steps")).toBeTruthy();
  });

  it("shows the Stopped header and terminal row after a user cancel", () => {
    const { turnGroups, state } = turnGroupsFor([
      reasoningStart(),
      reasoningDelta("partial thought"),
      overallStop(StopReason.USER_CANCELLED),
    ]);
    expect(state.stopReason).toBe(StopReason.USER_CANCELLED);

    render(
      <AgentTimeline
        turnGroups={turnGroups}
        chatState={chatState}
        stopPacketSeen
        stopReason={state.stopReason}
      />,
    );

    // Collapsed by default; the terminal Stopped row only exists in the expanded body.
    expect(screen.getByText("Interrupted Thinking")).toBeTruthy();
    expect(screen.queryByText("Stopped")).toBeNull();

    fireEvent.press(screen.getByText("1 step"));
    expect(screen.getByText("Stopped")).toBeTruthy();
    expect(screen.getByText("partial thought")).toBeTruthy();
  });

  it("renders only the avatar row when there is an answer but no steps", () => {
    render(
      <AgentTimeline turnGroups={[]} chatState={chatState} hasDisplayContent />,
    );
    expect(screen.queryByText("Thinking...")).toBeNull();
    expect(screen.queryByText("Thought for some time")).toBeNull();
  });

  describe("parallel turns", () => {
    const parallelPackets = [
      makePlacedPacket({ type: "reasoning_start" }, { tab_index: 0 }),
      makePlacedPacket(
        { type: "reasoning_delta", reasoning: "branch one thinking" },
        { tab_index: 0 },
      ),
      makePlacedPacket(
        { type: "search_tool_start", is_internet_search: true },
        { tab_index: 1 },
      ),
    ];

    it("is detected as a parallel turn group", () => {
      const { turnGroups } = turnGroupsFor(parallelPackets);
      expect(turnGroups[0]?.isParallel).toBe(true);
      expect(turnGroups[0]?.steps).toHaveLength(2);
    });

    it("shows a pill tab per branch in the streaming header", () => {
      const { turnGroups } = turnGroupsFor(parallelPackets);
      render(<AgentTimeline turnGroups={turnGroups} chatState={chatState} />);

      // "Thinking" also appears as the collapsed preview's status, so assert on the unique label.
      expect(screen.getByText("Web Search")).toBeTruthy();
      expect(screen.getAllByText("Thinking").length).toBeGreaterThan(0);
    });

    it("shows the branch tab strip in the expanded body", () => {
      const { turnGroups } = turnGroupsFor([...parallelPackets, overallStop()]);
      render(
        <AgentTimeline
          turnGroups={turnGroups}
          chatState={chatState}
          stopPacketSeen
          hasDisplayContent
          processingDurationSeconds={3}
        />,
      );

      expect(screen.queryByText("Web Search")).toBeNull();
      fireEvent.press(screen.getByText("2 steps"));

      expect(screen.getByText("Web Search")).toBeTruthy();
      // The first branch is selected, so its reasoning body renders below the tabs.
      expect(screen.getByText("branch one thinking")).toBeTruthy();
    });

    it("swaps the rendered branch when another tab is selected", () => {
      const { turnGroups } = turnGroupsFor([...parallelPackets, overallStop()]);
      render(
        <AgentTimeline
          turnGroups={turnGroups}
          chatState={chatState}
          stopPacketSeen
          hasDisplayContent
          processingDurationSeconds={3}
        />,
      );
      fireEvent.press(screen.getByText("2 steps"));
      expect(screen.getByText("branch one thinking")).toBeTruthy();

      fireEvent.press(screen.getByText("Web Search"));
      // No search renderer is registered yet, so the branch body is empty rather than reasoning.
      expect(screen.queryByText("branch one thinking")).toBeNull();
    });
  });
});
