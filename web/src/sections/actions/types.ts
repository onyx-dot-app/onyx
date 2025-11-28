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
