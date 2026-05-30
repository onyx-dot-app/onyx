// packetProcessor.ts — pure packet → message-tree reducer.
//
// `applyPacket(tree, packet)` appends ONE streaming `Packet` to the assistant message
// it belongs to and advances that message's cached/derived fields (visible text,
// documents, citations). It is a pure function: it returns a NEW MessageTreeState and
// never mutates the input (the target Message and its `packets` array are cloned).
//
// What this ports from web:
//   - The streaming send loop in web (services/lib.tsx + currentMessageFIFO.ts) appends
//     raw `Packet`s onto the in-flight assistant Message's `packets` array, keyed by
//     `placement.model_index` for multi-model. We reproduce just that append-and-derive
//     step here as a testable reducer.
//   - The "derive content from packets" helpers mirror web's services/packetUtils.ts
//     (getTextContent / getCitations) and the document accumulation in
//     message/.../timeline/hooks/packetProcessor.ts (handleDocumentPacket).
//
// What this intentionally DROPS (out of scope per design doc 06):
//   - web's UI grouping / timeline transform (toolGroups, displayGroups, turn grouping).
//   - the typewriter pacing hooks (usePacedTurnGroups / usePacedMessageSwitching).
//   These are presentation concerns layered on top of `packets`; this reducer only owns
//   the tree's source-of-truth `packets` array + the cheap cached fields read off it.
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

// ── Derivation helpers (ported from web packetUtils.ts) ───────────────────────

/** Concatenate the visible text content carried by MESSAGE_START / MESSAGE_DELTA packets. */
export function getTextContent(packets: Packet[]): string {
  return packets
    .map((packet) => {
      if (
        packet.obj.type === PacketType.MESSAGE_START ||
        packet.obj.type === PacketType.MESSAGE_DELTA
      ) {
        return (packet.obj as MessageStart | MessageDelta).content || "";
      }
      return "";
    })
    .join("");
}

/** Build the citation_num → document_id map from CITATION_INFO packets. */
export function getCitationMap(packets: Packet[]): CitationMap {
  const citationMap: CitationMap = {};
  for (const packet of packets) {
    if (packet.obj.type === PacketType.CITATION_INFO) {
      const info = packet.obj as CitationInfo;
      citationMap[info.citation_number] = info.document_id;
    }
  }
  return citationMap;
}

/** Collect every document delivered by search / fetch tool packets, de-duplicated by id. */
export function getDocuments(packets: Packet[]): OnyxDocument[] {
  const byId = new Map<string, OnyxDocument>();
  for (const packet of packets) {
    let docs: OnyxDocument[] | null | undefined;
    if (packet.obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA) {
      docs = (packet.obj as SearchToolDocumentsDelta).documents;
    } else if (packet.obj.type === PacketType.FETCH_TOOL_DOCUMENTS) {
      docs = (packet.obj as FetchToolDocuments).documents;
    }
    if (docs) {
      for (const doc of docs) {
        if (doc.document_id) byId.set(doc.document_id, doc);
      }
    }
  }
  return Array.from(byId.values());
}

/** True once a STOP packet has been seen for this message. */
export function isStreamingComplete(packets: Packet[]): boolean {
  return packets.some((p) => p.obj.type === PacketType.STOP);
}

// ── Target-node resolution ────────────────────────────────────────────────────
// Mirrors web's streaming loop, which routes a packet to a specific in-flight
// assistant message. Resolution order:
//   1. An explicit target nodeId (the caller already knows which node is streaming).
//   2. placement.model_index — for multi-model parallel generation, the i-th assistant
//      child of the latest user message in the current chain.
//   3. The latest assistant leaf of the current message chain (the single-model case).
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
    // Find the latest user message in the chain; its assistant children are the
    // per-model response slots. Pick the one at `model_index`.
    for (let i = chain.length - 1; i >= 0; i--) {
      const node = chain[i];
      if (node && node.type === "user") {
        const childId = (node.childrenNodeIds ?? [])[modelIndex];
        if (childId !== undefined && tree.has(childId)) return childId;
        break;
      }
    }
  }

  // Default: the latest assistant message in the chain.
  for (let i = chain.length - 1; i >= 0; i--) {
    const node = chain[i];
    if (node && node.type === "assistant") return node.nodeId;
  }
  return undefined;
}

// ── The reducer ────────────────────────────────────────────────────────────────

/**
 * Append `packet` to its assistant message in `tree` and refresh that message's
 * derived fields. Returns a new tree; the input is never mutated.
 *
 * @param tree           current message tree
 * @param packet         the streaming packet to apply
 * @param targetNodeId   optional explicit target (the caller's known in-flight node)
 */
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

  // Append the packet (clone the array — never mutate the stored one).
  const packets = [...existing.packets, packet];

  // Derive cached fields off the full packet list (cheap; arrays are small).
  const message = getTextContent(packets);
  const citations = getCitationMap(packets);
  const documents = getDocuments(packets);

  // Capture stop reason if this packet (or any prior) was a STOP.
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
    documents: documents.length > 0 ? documents : existing.documents,
    stopReason,
  };

  const newTree = new Map(tree);
  newTree.set(nodeId, updated);
  return newTree;
}

/**
 * Convenience: apply a batch of packets in order. Equivalent to folding `applyPacket`
 * over `packets`. Useful when replaying a buffered chunk.
 */
export function applyPackets(
  tree: MessageTreeState,
  packets: Packet[],
  targetNodeId?: number
): MessageTreeState {
  return packets.reduce(
    (acc, packet) => applyPacket(acc, packet, targetNodeId),
    tree
  );
}
