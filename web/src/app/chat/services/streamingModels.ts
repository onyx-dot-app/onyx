import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";

// Base interface for all streaming objects
interface BaseObj {
  type: string;
}

export enum PacketType {
  MESSAGE_START = "message_start",
  MESSAGE_DELTA = "message_delta",
  MESSAGE_END = "message_end",

  STOP = "stop",

  TOOL_START = "tool_start",
  TOOL_DELTA = "tool_delta",
  TOOL_END = "tool_end",
}

// LlmDoc interface matching the backend model
export interface LlmDoc {
  document_id: string;
  content: string;
  blurb: string;
  semantic_identifier: string;
  source_type: ValidSources;
  metadata: { [key: string]: string | string[] };
  updated_at: string | null;
  link: string | null;
  source_links: { [key: number]: string } | null;
  match_highlights: string[] | null;
}

// Basic Message Packets
export interface MessageStart extends BaseObj {
  id: string;
  type: "message_start";
  content: string;
}

export interface MessageDelta extends BaseObj {
  content: string;
  type: "message_delta";
}

export interface MessageEnd extends BaseObj {
  type: "message_end";
}

// Control Packets
export interface Stop extends BaseObj {
  type: "stop";
}

// Tool Packets
export interface ToolStart extends BaseObj {
  type: "tool_start";
  tool_name: string;
  tool_icon: string;
  // if left blank, we will use the tool name
  tool_main_description: string | null;
}

export interface ToolDelta extends BaseObj {
  type: "tool_delta";
  documents: OnyxDocument[] | null;
  images: Array<{ [key: string]: string }> | null;
}

export interface ToolEnd extends BaseObj {
  type: "tool_end";
}

export type ChatObj = MessageStart | MessageDelta | MessageEnd;

export type StopObj = Stop;

export type ToolObj = ToolStart | ToolDelta | ToolEnd;

// Union type for all possible streaming objects
export type ObjTypes = ChatObj | ToolObj | StopObj;

// Packet wrapper for streaming objects
export interface Packet {
  ind: number;
  obj: ObjTypes;
}

export interface ChatPacket {
  ind: number;
  obj: ChatObj;
}

export interface ToolPacket {
  ind: number;
  obj: ToolObj;
}

export interface StopPacket {
  ind: number;
  obj: StopObj;
}
