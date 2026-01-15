import { JSX } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { Packet, StopReason } from "../../services/streamingModels";
import { OnyxDocument, MinimalOnyxDocument } from "@/lib/search/interfaces";
import { ProjectFile } from "../../projects/projectsService";
import { LlmDescriptor } from "@/lib/hooks";
import { IconType } from "react-icons";
import { OnyxIconType } from "@/components/icons/icons";
import { CitationMap } from "../../interfaces";

export enum RenderType {
  HIGHLIGHT = "highlight",
  FULL = "full",
}

export interface FullChatState {
  assistant: MinimalPersonaSnapshot;
  // Document-related context for citations
  docs?: OnyxDocument[] | null;
  userFiles?: ProjectFile[];
  citations?: CitationMap;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
  // Regenerate functionality
  regenerate?: (modelOverRide: LlmDescriptor) => Promise<void>;
  overriddenModel?: string;
  researchType?: string | null;
}

export interface RendererResult {
  icon: IconType | OnyxIconType | null;
  status: string | JSX.Element | null;
  content: JSX.Element;

  // can be used to override the look on the "expanded" view
  // used for things that should just show text w/o an icon or header
  // e.g. ReasoningRenderer
  expandedText?: JSX.Element;
}

export type MessageRenderer<
  T extends Packet,
  S extends Partial<FullChatState>,
> = React.ComponentType<{
  packets: T[];
  state: S;
  onComplete: () => void;
  renderType: RenderType;
  animate: boolean;
  stopPacketSeen: boolean;
  stopReason?: StopReason;
  children: (result: RendererResult) => JSX.Element;
}>;
