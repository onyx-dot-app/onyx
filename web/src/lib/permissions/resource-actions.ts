// Per-resource action vocabularies, hand-written to match the keys the server stamps
// on each resource's `permissions` map. A backend coverage test guards that the server
// never stamps a key absent here, so this stays in sync without a codegen pipeline.

// `A` is the resource's own action union, inferred back out of `permissions` at the call
// site so `can()` rejects another resource's action. Constrained to real action literals,
// so an untagged `Record<string, boolean>` is rejected rather than silently unchecked.
export interface WithPermissions<
  A extends AnyResourceAction = AnyResourceAction,
> {
  permissions?: Partial<Record<A, boolean>>;
}

// One entry per projection in the backend's permission_projection.py. The key names the
// resource, not the DTO carrying it: CCPair covers both the list row and the detail DTO,
// and Action covers OpenAPI + MCP tools — each group shares a single backend projection.
export const RESOURCE_ACTIONS = {
  CCPair: ["edit", "delete", "publish"],
  Agent: [
    "edit",
    "share",
    "view_stats",
    "delete",
    "publish",
    "feature",
    "list",
    "reorder",
  ],
  DocumentSet: ["edit", "manage_access", "delete", "publish"],
  Action: ["edit", "delete", "toggle", "authenticate"],
  MCPServer: ["edit", "delete", "authenticate", "manage_status"],
  CustomSkill: ["edit", "manage_access", "delete", "publish"],
  UserGroup: ["manage", "delete", "edit_permissions", "edit_token_limits"],
} as const;

export type ResourceName = keyof typeof RESOURCE_ACTIONS;
export type ResourceAction<R extends ResourceName> =
  (typeof RESOURCE_ACTIONS)[R][number];

// Union of all actions — makes a typo a compile error, not a silent false.
export type AnyResourceAction = ResourceAction<ResourceName>;

// Declare a resource's map as `permissions?: PermissionsOf<"CustomSkill">` to tie it to
// that vocabulary. Partial because a path that doesn't stamp sends `{}`.
export type PermissionsOf<R extends ResourceName> = Partial<
  Record<ResourceAction<R>, boolean>
>;

// Fail-closed: a missing resource or unstamped key reads as false, so a control the
// server hasn't authorized (or a new action an older client predates) never renders.
export function can<A extends AnyResourceAction>(
  resource: WithPermissions<A> | null | undefined,
  action: A
): boolean {
  return resource?.permissions?.[action] ?? false;
}
