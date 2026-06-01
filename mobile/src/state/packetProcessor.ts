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

// ── Incremental single-packet derivation (perf) ───────────────────────────────
// `applyPacket` runs once per streamed packet, so deriving cached fields from a
// single packet (O(1)) rather than re-scanning the whole array (O(n) per packet
// = O(n²) over a stream) keeps streaming smooth on-device.

/** The visible text contributed by a single MESSAGE_START / MESSAGE_DELTA packet. */
function textDeltaOf(packet: Packet): string {
  if (
    packet.obj.type === PacketType.MESSAGE_START ||
    packet.obj.type === PacketType.MESSAGE_DELTA
  ) {
    return (packet.obj as MessageStart | MessageDelta).content || "";
  }
  return "";
}

/** Merge a single packet's CITATION_INFO into an existing citation map (new object only when it changes). */
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

/** Merge a single packet's search/fetch documents into an existing list, de-duped by id (last wins, order preserved). */
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

  // Derive cached fields INCREMENTALLY from just the new packet (O(1)).
  // Re-scanning the whole array per packet would be O(n²) over a long stream
  // (thousands of MESSAGE_DELTA packets) and is the main streaming-jank risk.
  const delta = textDeltaOf(packet);
  const message = delta ? existing.message + delta : existing.message;
  const citations = mergeCitation(existing.citations, packet);
  const documents = mergeDocuments(existing.documents, packet);

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
    documents,
    stopReason,
  };

  const newTree = new Map(tree);
  newTree.set(nodeId, updated);
  return newTree;
}
