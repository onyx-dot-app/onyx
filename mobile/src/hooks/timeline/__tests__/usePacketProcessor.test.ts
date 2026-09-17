import { act, renderHook } from "@testing-library/react-native";
import { describe, expect, it } from "@jest/globals";
import {
  makeMessageStartPacket,
  makeStopPacket,
  makeItem,
  packetForItem,
} from "@/chat/__tests__/fixtures";
import { Packet } from "@/chat/streamingModels";
import { usePacketProcessor } from "@/hooks/timeline/usePacketProcessor";

describe("usePacketProcessor", () => {
  it("waits for rendering after the stream stops, then resets for another message", () => {
    const packets = [
      packetForItem(
        makeItem({
          kind: "text",
          text: "Answer",
          purpose: "answer",
          status: "complete",
          documents: [],
          citations: [],
        }),
      ),
      makeStopPacket(),
    ];
    const { result, rerender } = renderHook(
      ({ nodeId }: { nodeId: number }) => usePacketProcessor(packets, nodeId),
      { initialProps: { nodeId: 1 } },
    );
    expect(result.current.stopPacketSeen).toBe(true);
    expect(result.current.isComplete).toBe(false);
    act(() => result.current.onRenderComplete());
    expect(result.current.isComplete).toBe(true);
    rerender({ nodeId: 2 });
    expect(result.current.isComplete).toBe(false);
  });
  it("resets stream state when a regenerated response has fewer packets", () => {
    const { result, rerender } = renderHook(
      ({ packets }: { packets: Packet[] }) => usePacketProcessor(packets, 1),
      {
        initialProps: { packets: [makeMessageStartPacket(), makeStopPacket()] },
      },
    );
    expect(result.current.stopPacketSeen).toBe(true);
    rerender({ packets: [makeMessageStartPacket()] });
    expect(result.current.stopPacketSeen).toBe(false);
    expect(result.current.isComplete).toBe(false);
  });
});
