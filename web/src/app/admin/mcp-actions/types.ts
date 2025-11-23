import { MCPServer, ToolSnapshot } from "@/lib/tools/interfaces";
import { KeyedMutator } from "swr";
import { MCPServersResponse } from "@/lib/tools/interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";

export type MCPServerStatus = "CREATED" | "AWAITING_AUTH" | "CONNECTED";
export type MCPActionStatus = "connected" | "pending" | "disconnected";

// Extended interface with status field
export interface MCPServerWithStatus
  extends Omit<MCPServer, "transport" | "auth_type" | "auth_performer"> {
  status: MCPServerStatus;
  transport: string | null;
  auth_type: string | null;
  auth_performer: string | null;
}

export interface MCPActionsListProps {
  mcpServers: MCPServerWithStatus[];
  toolsByServer: Record<number, ToolSnapshot[]>;
  mutateMcpServers: KeyedMutator<MCPServersResponse>;
  mutateTools: KeyedMutator<ToolSnapshot[]>;
  setPopup: (spec: PopupSpec) => void;
}

export interface MCPServerCreateRequest {
  name: string;
  description?: string;
  server_url: string;
}
