import type React from "react";
import { MCPServer } from "@/lib/tools/interfaces";

export enum MCPActionStatus {
  CONNECTED = "connected",
  PENDING = "pending",
  DISCONNECTED = "disconnected",
  FETCHING = "fetching",
}

export enum MCPServerStatus {
  CREATED = "CREATED",
  AWAITING_AUTH = "AWAITING_AUTH",
  FETCHING_TOOLS = "FETCHING_TOOLS",
  CONNECTED = "CONNECTED",
  DISCONNECTED = "DISCONNECTED",
}

// Extended interface with status field
export interface MCPServerWithStatus
  extends Omit<MCPServer, "transport" | "auth_type" | "auth_performer"> {
  status: MCPServerStatus;
  transport: string | null;
  auth_type: string | null;
  auth_performer: string | null;
  tool_count: number;
}

export interface MCPServerCreateRequest {
  name: string;
  description?: string;
  server_url: string;
}

export interface MCPServerUpdateRequest {
  name?: string;
  description?: string;
  server_url?: string;
}

export interface MCPTool {
  id: string;
  name: string;
  description: string;
  icon?: React.ReactNode;
  isAvailable: boolean;
  isEnabled: boolean;
}

export interface MethodSpec {
  /* Defines a single method that is part of a custom tool. Each method maps to a single
  action that the LLM can choose to take. */
  name: string;
  summary: string;
  path: string;
  method: string;
  spec: Record<string, any>;
  custom_headers: { key: string; value: string }[];
}
