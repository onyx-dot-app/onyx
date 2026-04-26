import {
  hasAnyAdminPermission,
  hasPermission,
  getFirstPermittedAdminRoute,
} from "./permissions";
import { ADMIN_ROUTES } from "./admin-routes";
import { Permission } from "./types";

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
