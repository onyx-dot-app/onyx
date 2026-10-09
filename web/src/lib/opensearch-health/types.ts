export type ResourceIssue = "disk" | "jvm_memory" | "vector_memory";

export interface ResourceHealth {
  checked_at: string | null;
  issues: ResourceIssue[];
  stale: boolean;
}

export interface ResourcePopupResponse {
  show_popup: boolean;
  health: ResourceHealth;
}
