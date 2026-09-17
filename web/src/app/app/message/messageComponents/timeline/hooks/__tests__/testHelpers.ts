import {
  ChatItem,
  Packet,
  PacketIdentity,
  Placement,
  ResponseItem,
  StopReason,
} from "@/app/app/services/streamingModels";

export function responseItem(
  content: ChatItem,
  placement: Placement = { turn_index: 0, tab_index: 0 },
  identity: Partial<PacketIdentity> = {}
): ResponseItem {
  return {
    identity: {
      response_id: 1,
      run_id: "root",
      message_id: `message-${placement.turn_index}`,
      part_id: content.kind,
      ...identity,
    },
    placement,
    content,
  };
}

export function itemPacket(item: ResponseItem): Packet {
  return {
    identity: item.identity,
    obj: { type: "item_update", item: item.content },
  };
}

export function toolItem(
  turnIndex = 0,
  tabIndex = 0,
  name = "internal_search"
): ResponseItem {
  return responseItem(
    {
      kind: "tool",
      name,
      arguments: {},
      status: "running",
      output: "",
      metadata: null,
    },
    { turn_index: turnIndex, tab_index: tabIndex },
    { tool_call_id: `tool-${turnIndex}-${tabIndex}` }
  );
}

export function answerItem(turnIndex = 1, text = "Answer"): ResponseItem {
  return responseItem(
    {
      kind: "text",
      text,
      status: "complete",
      purpose: "answer",
      documents: [],
      citations: [],
    },
    { turn_index: turnIndex, tab_index: 0 }
  );
}

export function stopPacket(): Packet {
  return {
    obj: { type: "stop", stop_reason: StopReason.FINISHED },
  };
}
