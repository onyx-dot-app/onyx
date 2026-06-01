// Pure packet → message-tree reducer. Mirrors web's append-and-derive packet step
// (services/lib.tsx streaming loop + packetUtils.ts), as a testable reducer.
//
// Intentionally drops web's presentation layer (UI grouping/timeline transform,
// typewriter pacing hooks); those are layered on top of `packets`. This reducer
// owns only the source-of-truth `packets` array and the cached fields read off it.
import {
  Packet,
  PacketType,
  MessageStart,
  MessageDelta,
  CitationInfo,
  SearchToolDocumentsDelta,
  FetchToolDocuments,
  OnyxDocument,
  CitationMap,
  StreamStopReason,
  Message,
} from "@/lib/types";
import { MessageTreeState, getLatestMessageChain } from "./messageTree";

// applyPacket runs once per streamed packet, so cached fields are derived from a
// single packet (O(1)) rather than re-scanning the whole array (O(n²) over a
// stream) to keep streaming smooth on-device.
function textDeltaOf(packet: Packet): string {
  if (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.MESSAGE_DELTA
  ) {
    return (packet.obj as MessageStart | MessageDelta).content || "";
  }
  return "";
}

// New object only when the map actually changes.
function mergeCitation(
  existing: CitationMap | undefined,
  packet: Packet
): CitationMap | undefined {
  if (packet.obj.type !== PacketType.CITATION_INFO) return existing;
  const info = packet.obj as CitationInfo;
  const base = existing ?? {};
  if (base[info.citation_number] === info.document_id) return existing;
  return { ...base, [info.citation_number]: info.document_id };
}

// De-dupe by id: last wins, order preserved.
function mergeDocuments(
  existing: OnyxDocument[] | null | undefined,
  packet: Packet
): OnyxDocument[] | null | undefined {
  let incoming: OnyxDocument[] | null | undefined;
  if (packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA) {
    incoming = (packet.obj as SearchToolDocumentsDelta).documents;
  } else if (packet.obj.type === PacketType.FETCH_TOOL_DOCUMENTS) {
    incoming = (packet.obj as FetchToolDocuments).documents;
  }
  if (!incoming || incoming.length === 0) return existing;

  const next = existing ? [...existing] : [];
  const indexById = new Map<string, number>();
  next.forEach((doc, i) => {
    if (doc.document_id) indexById.set(doc.document_id, i);
  });
  for (const doc of incoming) {
    if (!doc.document_id) continue;
    const at = indexById.get(doc.document_id);
    if (at === undefined) {
      indexById.set(doc.document_id, next.length);
      next.push(doc);
    } else {
      next[at] = doc; // last wins, mirrors web documentMap.set
    }
  }
  return next;
}

// Routes a packet to a specific in-flight assistant message. Resolution order:
//   1. explicit target nodeId,
//   2. placement.model_index — the i-th assistant child of the latest user
//      message in the chain (multi-model parallel generation),
//   3. the latest assistant leaf of the chain (single-model).
function resolveTargetNodeId(
  tree: MessageTreeState,
  packet: Packet,
  explicitNodeId?: number
): number | undefined {
  if (explicitNodeId !== undefined && tree.has(explicitNodeId)) {
    return explicitNodeId;
  }

  const chain = getLatestMessageChain(tree);
  if (chain.length === 0) return undefined;

  const modelIndex = packet.placement.model_index;
  if (modelIndex !== null && modelIndex !== undefined) {
    // The latest user message's assistant children are the per-model slots.
    for (let i = chain.length - 1; i >= 0; i--) {
      const node = chain[i];
      if (node && node.type === "user") {
        const childId = (node.childrenNodeIds ?? [])[modelIndex];
        if (childId !== undefined && tree.has(childId)) return childId;
        break;
      }
    }
  }

  for (let i = chain.length - 1; i >= 0; i--) {
    const node = chain[i];
    if (node && node.type === "assistant") return node.nodeId;
  }
  return undefined;
}

// Append `packet` to its assistant message and refresh that message's derived
// fields. Returns a new tree; the input is never mutated.
export function applyPacket(
  tree: MessageTreeState,
  packet: Packet,
  targetNodeId?: number
): MessageTreeState {
  const nodeId = resolveTargetNodeId(tree, packet, targetNodeId);
  if (nodeId === undefined) {
    // Nothing to attach to (e.g. metadata packet before any assistant node exists).
    return tree;
  }

  const existing = tree.get(nodeId);
  if (!existing) return tree;

  // Clone the array — never mutate the stored one.
  const packets = [...existing.packets, packet];

  // Derive incrementally from just the new packet (O(1)). Re-scanning the whole
  // array per packet would be O(n²) over a long stream and is the main jank risk.
  const delta = textDeltaOf(packet);
  const message = delta ? existing.message + delta : existing.message;
  const citations = mergeCitation(existing.citations, packet);
  const documents = mergeDocuments(existing.documents, packet);

  let stopReason: StreamStopReason | null | undefined = existing.stopReason;
  if (packet.obj.type === PacketType.STOP) {
    // streamingModels' StopReason ("finished"|"user_cancelled") overlaps the
    // domain StreamStopReason union; carry the raw value through.
    const reason = (packet.obj as { stop_reason?: string }).stop_reason;
    stopReason = (reason as StreamStopReason | undefined) ?? stopReason;
  }

  const updated: Message = {
    ...existing,
    packets,
    packetCount: packets.length,
    message,
    citations,
    documents,
    stopReason,
  };

  const newTree = new Map(tree);
  newTree.set(nodeId, updated);
  return newTree;
}
