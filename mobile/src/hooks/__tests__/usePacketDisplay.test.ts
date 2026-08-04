import { describe, expect, it } from "@jest/globals";
import { renderHook } from "@testing-library/react-native";

import { makeMessageStartPacket, makePacket } from "@/chat/__tests__/fixtures";
import { type Message } from "@/chat/interfaces";
import { type Packet } from "@/chat/streamingModels";
import { usePacketDisplay } from "@/hooks/usePacketDisplay";

function makeAssistantNode(packets: Packet[]): Message {
  return {
    nodeId: 1,
    parentNodeId: 0,
    type: "assistant",
    message: "",
    files: [],
    packets,
  };
}

const reasoningPackets: Packet[] = [
  makePacket({ type: "reasoning_start" }),
  makePacket({ type: "reasoning_delta", reasoning: "thinking hard" }),
  makePacket({ type: "reasoning_done" }),
];

describe("usePacketDisplay", () => {
  it("reports no display content before the answer starts", () => {
    const { result } = renderHook(() =>
      usePacketDisplay(makeAssistantNode([])),
    );
    expect(result.current.hasDisplayContent).toBe(false);
  });

  // Keying the gate on "findRenderer matched something" instead would put raw reasoning text in the
  // answer slot and kill the loader — reasoning and tool groups belong above the answer, not in it.
  it("stays closed for a reasoning-only node", () => {
    const { result } = renderHook(() =>
      usePacketDisplay(makeAssistantNode(reasoningPackets)),
    );
    expect(result.current.hasDisplayContent).toBe(false);
  });

  it("opens once the answer's message_start arrives in the next turn", () => {
    const { result } = renderHook(() =>
      usePacketDisplay(
        // The backend increments turn_index before the answer, so the answer is always its own
        // group (backend/onyx/chat/llm_step.py).
        makeAssistantNode([
          ...reasoningPackets,
          { ...makeMessageStartPacket(), placement: { turn_index: 1 } },
        ]),
      ),
    );
    expect(result.current.hasDisplayContent).toBe(true);
  });

  it("still exposes the processed state consumers read (citations, completion)", () => {
    const { result } = renderHook(() =>
      usePacketDisplay(
        makeAssistantNode([
          makeMessageStartPacket(),
          makePacket({ type: "message_delta", content: "hi" }),
          makePacket({ type: "message_end" }),
        ]),
      ),
    );
    expect(result.current.processed.isComplete).toBe(true);
    expect(result.current.packets).toHaveLength(3);
  });
});
