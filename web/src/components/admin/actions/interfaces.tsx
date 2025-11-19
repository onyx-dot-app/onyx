import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPTransportType,
} from "@/lib/tools/interfaces";
import { PopupSpec } from "../connectors/Popup";

export interface MCPTool {
  name: string;
  description?: string;
  displayName?: string;
  inputSchema?: Record<string, any>;
}

export interface ToolListResponse {
  server_name: string;
  server_url: string;
  tools: MCPTool[];
}

export interface MCPAuthTemplate {
  headers: Record<string, string>;
  required_fields: string[];
}

export interface MCPFormValues {
  name: string;
  description: string;
  server_url: string;
  transport: MCPTransportType;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  api_token: string;
  auth_template?: MCPAuthTemplate;
  user_credentials?: Record<string, string>;
  oauth_client_id?: string;
  oauth_client_secret?: string;
}

export interface ToolListProps {
  values: MCPFormValues;
  verbRoot: string;
  serverId: number | undefined;
  setPopup: (popup: PopupSpec | null) => void;
  oauthConnected: boolean;
}

export interface MCPServerDetail {
  id: number;
  name: string;
  server_url: string;
  transport: MCPTransportType;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  description: string | null;
  is_authenticated: boolean;
  auth_template: MCPAuthTemplate | null;
  admin_credentials: Record<string, string> | null; // "api_key": value
  user_credentials: Record<string, string> | null; // map from placeholder to value
}
