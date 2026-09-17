import { PacketIdentity, Placement } from "@/chat/streamingModels";

interface ResponseLayout {
  nextTurn: number;
  groups: Map<string, number>;
  tabs: Map<string, Map<string, number>>;
  calls: Map<string, Placement>;
  childParts: Map<string, Map<string, number>>;
}

function callKey(messageId: string, callId: string): string {
  return JSON.stringify([messageId, callId]);
}

/** Derive timeline positions from execution identity for live and saved packets. */
export class PacketLayout {
  private readonly responses = new Map<number, ResponseLayout>();
  place(identity: PacketIdentity, modelIndex: number): Placement {
    let response = this.responses.get(identity.response_id);
    if (!response) {
      response = {
        nextTurn: 0,
        groups: new Map(),
        tabs: new Map(),
        calls: new Map(),
        childParts: new Map(),
      };
      this.responses.set(identity.response_id, response);
    }
    const parentKey =
      identity.parent_message_id && identity.parent_tool_call_id
        ? callKey(identity.parent_message_id, identity.parent_tool_call_id)
        : undefined;
    const parent = parentKey ? response.calls.get(parentKey) : undefined;
    if (parentKey && !parent) {
      throw new Error(`Missing parent tool identity: ${parentKey}`);
    }
    let placement: Placement;
    if (parentKey && parent) {
      const groupKey = `${parent.turn_index}:${parent.tab_index ?? 0}`;
      let parts = response.childParts.get(groupKey);
      if (!parts) {
        parts = new Map();
        response.childParts.set(groupKey, parts);
      }
      const partKey = JSON.stringify([
        identity.message_id,
        identity.tool_call_id,
        identity.part_id,
      ]);
      let subTurn = parts.get(partKey);
      if (subTurn === undefined) {
        subTurn = parts.size;
        parts.set(partKey, subTurn);
      }
      placement = { ...parent, sub_turn_index: subTurn };
    } else {
      placement = this.rootPlacement(response, identity, modelIndex);
    }
    if (identity.tool_call_id) {
      response.calls.set(
        callKey(identity.message_id, identity.tool_call_id),
        placement,
      );
    }
    return placement;
  }

  private rootPlacement(
    response: ResponseLayout,
    identity: PacketIdentity,
    modelIndex: number,
  ): Placement {
    const groupKey = JSON.stringify([
      identity.message_id,
      identity.tool_call_id ? "tools" : identity.part_id,
    ]);
    let turn = response.groups.get(groupKey);
    if (turn === undefined) {
      turn = response.nextTurn++;
      response.groups.set(groupKey, turn);
    }
    let tabs = response.tabs.get(groupKey);
    if (!tabs) {
      tabs = new Map();
      response.tabs.set(groupKey, tabs);
    }
    const tabKey = identity.tool_call_id ?? identity.part_id;
    let tab = tabs.get(tabKey);
    if (tab === undefined) {
      tab = tabs.size;
      tabs.set(tabKey, tab);
    }
    return { turn_index: turn, tab_index: tab, model_index: modelIndex };
  }
}
