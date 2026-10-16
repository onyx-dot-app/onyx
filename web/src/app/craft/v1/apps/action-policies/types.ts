import type {
  ActionPolicy,
  ExternalAppType,
} from "@/app/craft/v1/apps/registry";

export interface ActionPolicySettingView {
  action_id: string;
  normalised_name: string;
  description: string;
  effective_policy: ActionPolicy;
  workspace_policy: ActionPolicy;
  stored_policy: ActionPolicy | null;
  editable: boolean;
  lock_reason: "workspace_disabled" | "workspace_managed" | null;
}

export interface AppActionPoliciesView {
  gated_app_id: number;
  kind: "external_app" | "mcp_server";
  target_id: number;
  name: string;
  users_can_manage_policies: boolean;
  enabled: boolean | null;
  app_type?: ExternalAppType | null;
  actions: ActionPolicySettingView[];
}

export interface TaskAppActionPolicies {
  gated_app_id: number;
  enabled: boolean;
  action_policies: Record<string, ActionPolicy>;
}
