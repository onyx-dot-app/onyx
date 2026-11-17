export enum MCPTransportType {
  STDIO = "STDIO",
  STREAMABLE_HTTP = "STREAMABLE_HTTP",
  SSE = "SSE",
}

export interface MCPOAuthDiscovery {
  status: "metadata_found" | "metadata_missing" | "unreachable";
  supports_automatic_registration: boolean | null;
  supports_client_metadata: boolean | null;
  authorization_endpoint: string | null;
  token_endpoint: string | null;
}

export type MCPSetupProbeResult =
  | {
      kind: "public";
      transport: MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE;
      tool_count: number;
      server_name: string;
    }
  | {
      kind: "oauth";
      transport: MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE | null;
      discovery: MCPOAuthDiscovery;
    }
  | {
      kind: "auth_unknown";
      transport: MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE | null;
    }
  | { kind: "unreachable"; reason: "blocked" | "connection_failed" };

export interface MCPProbeProgress {
  type: "progress";
  stage: "contacting_server" | "authentication";
  state: "pending" | "success" | "error";
}
