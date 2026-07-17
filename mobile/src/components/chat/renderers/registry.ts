// Packet-renderer dispatch seam. PR 9 adds rich renderers to RENDERERS; each is matched by the packet
// types in its group.
import type { ComponentType } from "react";

import { ProcessedMessageState } from "@/chat/messageProcessor";
import { Packet } from "@/chat/streamingModels";

import { MessageTextRenderer } from "./MessageTextRenderer";

export interface MessageRendererProps {
  packets: Packet[];
  // Processed packet state (citations, documents, completion). `processed.isComplete` is true once
  // message_end / stop is seen.
  processed: ProcessedMessageState;
}

export interface MessageRenderer {
  matches: (packets: Packet[]) => boolean;
  Component: ComponentType<MessageRendererProps>;
}

// first match wins
const RENDERERS: MessageRenderer[] = [MessageTextRenderer];

export function findRenderer(packets: Packet[]): MessageRenderer | null {
  return RENDERERS.find((renderer) => renderer.matches(packets)) ?? null;
}
