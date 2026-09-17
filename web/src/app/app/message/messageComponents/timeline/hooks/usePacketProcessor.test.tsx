import { renderHook } from "@testing-library/react";
import { usePacketProcessor } from "@/app/app/message/messageComponents/timeline/hooks/usePacketProcessor";
import {
  Packet,
  PacketIdentity,
  StopReason,
} from "@/app/app/services/streamingModels";

it("replaces saved history with a resumed stream before applying its deltas", () => {
  const identity: PacketIdentity = {
    response_id: 1,
    run_id: "root",
    message_id: "generation",
    part_id: "answer",
  };
  const history: Packet[] = [
    {
      identity,
      obj: {
        type: "item_update",
        item: {
          kind: "text",
          text: "Saved output",
          purpose: "answer",
          status: "complete",
          citations: [],
          documents: [],
        },
      },
    },
    { obj: { type: "stop", stop_reason: StopReason.FINISHED } },
  ];
  const { result, rerender } = renderHook(
    ({ packets }) => usePacketProcessor(packets, 1),
    { initialProps: { packets: history } }
  );
  expect(result.current.stopPacketSeen).toBe(true);

  const stream: Packet[] = [
    { identity, obj: { type: "run_update", status: "running" } },
    {
      identity: { ...identity, message_id: "resumed-generation" },
      obj: {
        type: "item_update",
        item: {
          kind: "text",
          text: "",
          purpose: "answer",
          status: "running",
          citations: [],
          documents: [],
        },
      },
    },
    {
      identity: { ...identity, message_id: "resumed-generation" },
      obj: {
        type: "item_delta",
        delta: { kind: "text", text: "Partial output", citations: [] },
      },
    },
  ];
  rerender({ packets: stream });
  expect(result.current.stopPacketSeen).toBe(false);
  expect(result.current.displayGroups).toHaveLength(1);
  expect(result.current.displayGroups[0]?.items[0]?.content).toMatchObject({
    text: "Partial output",
    status: "running",
  });

  rerender({ packets: [...stream] });
  expect(result.current.displayGroups[0]?.items[0]?.content).toMatchObject({
    text: "Partial output",
  });
});
