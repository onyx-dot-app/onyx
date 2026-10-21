import {
  ADMIN_ROUTES,
  matchAdminRoute,
  type FeatureFlags,
} from "@/lib/admin-routes";
import { buildItems } from "@/lib/admin-sidebar-utils";
import { Permission } from "@/lib/types";
import { Tier } from "@/lib/tiers/types";

const flags: FeatureFlags = {
  vectorDbEnabled: true,
  enableCloud: false,
  tier: Tier.COMMUNITY,
  customAnalyticsEnabled: false,
  hasSubscription: false,
  hooksEnabled: false,
  queryHistoryEnabled: false,
  craftAvailable: false,
};

test("shows one Plugins link for an action manager", () => {
  expect(
    buildItems([Permission.MANAGE_ACTIONS], flags, null).map((item) => ({
      nameId: item.nameId,
      link: item.link,
      disabled: item.disabled,
    }))
  ).toEqual([{ nameId: "plugins", link: "/admin/plugins", disabled: false }]);
});

test("omits Plugins without action management access", () => {
  const links = buildItems([Permission.MANAGE_AGENTS], flags, null).map(
    (item) => item.link
  );
  expect(links).toEqual(["/admin/agents"]);
});

test("full admins see the canonical link and no legacy action links", () => {
  const actionLinks = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    flags,
    null
  )
    .filter((item) => item.sectionId === "agentsAndActions")
    .map((item) => item.link);
  expect(actionLinks).toEqual(["/admin/agents", "/admin/plugins"]);
});

test("Craft-enabled admins have one Plugins entry and no separate Apps entry", () => {
  const links = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    { ...flags, craftAvailable: true },
    null
  ).map((item) => item.link);
  expect(links.filter((link) => link === "/admin/plugins")).toHaveLength(1);
  expect(links).not.toContain("/admin/craft/apps");
});

test.each(["/admin/plugins/external-app/7", "/admin/craft/apps"])(
  "retains full-admin authorization for %s",
  (pathname) => {
    expect(matchAdminRoute(pathname)?.requiredPermission).toBe(
      Permission.FULL_ADMIN_PANEL_ACCESS
    );
  }
);

test.each([
  "/admin/plugins",
  "/admin/plugins/mcp/7",
  "/admin/plugins/openapi/7",
  "/admin/mcp-actions",
  "/admin/mcp-actions/new",
  "/admin/mcp-actions/7",
  "/admin/openapi-actions",
])("gates %s with action management permission", (pathname) => {
  expect(matchAdminRoute(pathname)?.requiredPermission).toBe(
    Permission.MANAGE_ACTIONS
  );
});

test("matches canonical plugin details to the Plugins registry entry", () => {
  expect(matchAdminRoute("/admin/plugins/mcp/7")).toBe(ADMIN_ROUTES.PLUGINS);
});
