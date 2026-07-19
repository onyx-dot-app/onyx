import {
  hasAnyAdminPermission,
  hasPermission,
  getFirstPermittedAdminRoute,
  visibilityPermissions,
  SCOPED_MANAGER_PERMISSIONS,
} from "./permissions";
import { ADMIN_ROUTES } from "./admin-routes";
import { Permission, User } from "./types";

describe("hasPermission", () => {
  it("returns false for an empty permission set", () => {
    expect(hasPermission([], Permission.MANAGE_LLMS)).toBe(false);
  });

  it("returns true when the user holds the exact required permission", () => {
    expect(
      hasPermission([Permission.MANAGE_LLMS], Permission.MANAGE_LLMS)
    ).toBe(true);
  });

  it("returns false when the user holds a different permission", () => {
    expect(
      hasPermission([Permission.MANAGE_AGENTS], Permission.MANAGE_LLMS)
    ).toBe(false);
  });

  it("treats FULL_ADMIN_PANEL_ACCESS as an override for any required permission", () => {
    expect(
      hasPermission(
        [Permission.FULL_ADMIN_PANEL_ACCESS],
        Permission.MANAGE_LLMS
      )
    ).toBe(true);
  });

  it("returns true when any of the required permissions matches (OR semantics)", () => {
    expect(
      hasPermission(
        [Permission.MANAGE_AGENTS],
        Permission.MANAGE_LLMS,
        Permission.MANAGE_AGENTS
      )
    ).toBe(true);
  });

  it("returns false when none of the required permissions match", () => {
    expect(
      hasPermission(
        [Permission.READ_AGENTS],
        Permission.MANAGE_LLMS,
        Permission.MANAGE_AGENTS
      )
    ).toBe(false);
  });

  it("returns false when called with no required permissions and no override", () => {
    expect(hasPermission([Permission.MANAGE_AGENTS])).toBe(false);
  });

  it("returns true when called with no required permissions but the override is held", () => {
    expect(hasPermission([Permission.FULL_ADMIN_PANEL_ACCESS])).toBe(true);
  });
});

describe("hasAnyAdminPermission", () => {
  it("returns false for an empty permission set", () => {
    expect(hasAnyAdminPermission([])).toBe(false);
  });

  it("returns false when the user only holds non-admin permissions", () => {
    // BASIC_ACCESS is not gating any admin route — it should not unlock admin.
    expect(hasAnyAdminPermission([Permission.BASIC_ACCESS])).toBe(false);
  });

  it("returns true when the user holds FULL_ADMIN_PANEL_ACCESS", () => {
    expect(hasAnyAdminPermission([Permission.FULL_ADMIN_PANEL_ACCESS])).toBe(
      true
    );
  });

  it("returns true when the user holds any single admin-route permission", () => {
    expect(hasAnyAdminPermission([Permission.MANAGE_AGENTS])).toBe(true);
    expect(hasAnyAdminPermission([Permission.MANAGE_LLMS])).toBe(true);
    expect(hasAnyAdminPermission([Permission.MANAGE_USER_GROUPS])).toBe(true);
  });
});

describe("visibilityPermissions", () => {
  const asUser = (u: Partial<User>): User => u as User;

  it("returns the raw permissions for a non-manager", () => {
    const perms = visibilityPermissions(
      asUser({ effective_permissions: [Permission.BASIC_ACCESS] })
    );
    expect(perms).toEqual([Permission.BASIC_ACCESS]);
  });

  it("augments a manager with the scoped manage tokens", () => {
    const perms = visibilityPermissions(
      asUser({
        effective_permissions: [Permission.BASIC_ACCESS],
        is_group_manager: true,
      })
    );
    for (const token of SCOPED_MANAGER_PERMISSIONS) {
      expect(perms).toContain(token);
    }
    expect(perms).toContain(Permission.BASIC_ACCESS);
    // a manager should reach the admin area via those tokens
    expect(hasAnyAdminPermission(perms)).toBe(true);
  });

  it("does not grant full admin to a manager", () => {
    const perms = visibilityPermissions(
      asUser({ effective_permissions: [], is_group_manager: true })
    );
    expect(perms).not.toContain(Permission.FULL_ADMIN_PANEL_ACCESS);
  });

  it("returns an empty list for a null user", () => {
    expect(visibilityPermissions(null)).toEqual([]);
  });

  it("does not duplicate a token the manager already holds", () => {
    const perms = visibilityPermissions(
      asUser({
        effective_permissions: [Permission.MANAGE_CONNECTORS],
        is_group_manager: true,
      })
    );
    expect(
      perms.filter((p) => p === Permission.MANAGE_CONNECTORS)
    ).toHaveLength(1);
  });
});

describe("getFirstPermittedAdminRoute", () => {
  it("returns the first sidebar-labelled route for a full admin", () => {
    // FULL_ADMIN_PANEL_ACCESS unlocks every route — we expect the very first
    // entry in ADMIN_ROUTES declaration order that has a non-empty
    // sidebarLabel. Today that is LLM_MODELS.
    expect(
      getFirstPermittedAdminRoute([Permission.FULL_ADMIN_PANEL_ACCESS])
    ).toBe(ADMIN_ROUTES.LLM_MODELS.path);
  });

  it("returns the matching route when only one admin permission is held", () => {
    expect(getFirstPermittedAdminRoute([Permission.MANAGE_LLMS])).toBe(
      ADMIN_ROUTES.LLM_MODELS.path
    );
    expect(getFirstPermittedAdminRoute([Permission.MANAGE_AGENTS])).toBe(
      ADMIN_ROUTES.AGENTS.path
    );
  });

  it("falls back to /admin/agents when the user holds no admin permissions", () => {
    // Documented fallback — keeps the redirect target stable for the
    // ClientLayout loop-avoidance check.
    expect(getFirstPermittedAdminRoute([])).toBe(ADMIN_ROUTES.AGENTS.path);
  });
});
