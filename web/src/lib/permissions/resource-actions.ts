// Per-resource action vocabularies, hand-written to match the keys the server stamps
// on each resource's `permissions` map. A backend coverage test guards that the server
// never stamps a key absent here, so this stays in sync without a codegen pipeline.

export interface WithPermissions {
  permissions?: Record<string, boolean>;
}

export const RESOURCE_ACTIONS = {
  ConnectorIndexingStatusLite: ["edit", "delete", "publish"],
  CCPairFullInfo: ["edit", "delete", "publish"],
  ToolSnapshot: ["edit", "delete", "toggle"],
  MCPServer: ["edit", "delete", "authenticate", "manage_status"],
  CustomSkill: ["edit", "manage_access", "delete", "publish"],
  UserGroup: ["manage", "delete", "edit_permissions", "edit_token_limits"],
} as const;

export type ResourceName = keyof typeof RESOURCE_ACTIONS;
export type ResourceAction<R extends ResourceName> =
  (typeof RESOURCE_ACTIONS)[R][number];

// Fail-closed: a missing resource or unstamped key reads as false, so a control the
// server hasn't authorized (or a new action an older client predates) never renders.
export function can(
  resource: WithPermissions | null | undefined,
  action: string
): boolean {
  return resource?.permissions?.[action] ?? false;
}
