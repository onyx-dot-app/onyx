import { MCPServer } from "@/lib/tools/interfaces";

export type MCPServerStatus =
  | "CREATED"
  | "AWAITING_AUTH"
  | "CONNECTED"
  | "DISCONNECTED";
export type MCPActionStatus = "connected" | "pending" | "disconnected";

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
