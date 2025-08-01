import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { FeedbackType } from "../../interfaces";
import { Packet } from "../../services/streamingModels";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { FileResponse } from "../../my-documents/DocumentsContext";
import { LlmDescriptor } from "@/lib/hooks";
import { IconType } from "react-icons";

export enum AnimationType {
  FAST = "fast",
  SLOW = "slow",
  NONE = "none",
}

export interface FullChatState {
  handleFeedback: (feedback: FeedbackType) => void;
  assistant: MinimalPersonaSnapshot;
  // Document-related context for citations
  docs?: OnyxDocument[] | null;
  userFiles?: FileResponse[];
  citations?: { [key: string]: number };
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  // Regenerate functionality
  regenerate?: (modelOverRide: LlmDescriptor) => Promise<void>;
  overriddenModel?: string;
}

interface MessageRendererProps<
  T extends Packet,
  S extends Partial<FullChatState>,
> {
  packets: T[];
  state: S;
  onComplete: () => void;
  animationType: AnimationType;
}

export type MessageRenderer<
  T extends Packet,
  S extends Partial<FullChatState>,
> = ({
  packets,
  state,
  onComplete,
  animationType,
}: MessageRendererProps<T, S>) => JSX.Element;

export type FullRenderer<T extends Packet, S extends Partial<FullChatState>> = {
  icon: IconType | null;
  extendedRenderer: MessageRenderer<T, S>;
  shortRenderer: MessageRenderer<T, S>;
};
