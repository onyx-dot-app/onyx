import { MCPServer, ToolSnapshot } from "@/lib/tools/interfaces";
import { KeyedMutator } from "swr";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";

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

export interface MCPActionsListProps {
  mcpServers: MCPServerWithStatus[];
  mutateMcpServers: KeyedMutator<MCPServersResponse>;
  setPopup: (spec: PopupSpec) => void;
  toolsFetchingServerIds: string[];
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
