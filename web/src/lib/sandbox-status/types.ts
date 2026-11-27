/** Mirrors `backend/onyx/microvm/availability.py`. */

export type SandboxRuntime = "pod" | "firecracker" | "auto" | "off";

export type SandboxToolsOffReason =
  | "RUNTIME_WITHOUT_FIRECRACKER"
  | "TEMPLATE_NOT_CONFIGURED"
  | "NO_REGISTERED_NODE"
  | "NO_LIVE_NODE_WITH_TEMPLATE"
  | "NODE_STATE_UNREADABLE";

export interface SandboxNodeStatus {
  node_id: string;
  live: boolean;
  draining: boolean;
  has_template: boolean;
  last_report_age_seconds: number | null;
  agent_version: string | null;
  templates: string[];
  vm_count: number | null;
  // 0 is no cap.
  max_vms: number | null;
}

export interface SandboxStatus {
  runtime: SandboxRuntime;
  template: string;
  tools_offered: boolean;
  tools_off_reason: SandboxToolsOffReason | null;
  nodes: SandboxNodeStatus[];
}
