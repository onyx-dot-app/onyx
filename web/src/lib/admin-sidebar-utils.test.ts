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
  isPlayground: false,
  hooksEnabled: false,
  queryHistoryEnabled: false,
  craftAvailable: false,
};

test("offers Upgrade Plan to an admin without a subscription", () => {
  const items = buildItems([Permission.FULL_ADMIN_PANEL_ACCESS], flags, null);
  expect(items.map((item) => item.nameId)).toContain("upgradePlan");
});

test("hides Plans & Billing and Upgrade Plan on the playground", () => {
  const playground: FeatureFlags = { ...flags, isPlayground: true };
  const items = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    playground,
    null
  );
  expect(items.map((item) => item.nameId)).not.toContain("upgradePlan");
  expect(items.map((item) => item.link)).not.toContain(
    ADMIN_ROUTES.BILLING.path
  );

  const subscribed: FeatureFlags = { ...playground, hasSubscription: true };
  const links = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    subscribed,
    null
  ).map((item) => item.link);
  expect(links).not.toContain(ADMIN_ROUTES.BILLING.path);
});

test("shows Integrations to an action manager", () => {
  expect(
    buildItems([Permission.MANAGE_ACTIONS], flags, null).map((item) => ({
      nameId: item.nameId,
      link: item.link,
      sectionId: item.sectionId,
    }))
  ).toEqual([
    {
      nameId: "integrations",
      link: "/admin/integrations",
      sectionId: "agentsAndPlugins",
    },
  ]);
});

test("omits Integrations without action management access", () => {
  const links = buildItems([Permission.MANAGE_AGENTS], flags, null).map(
    (item) => item.link
  );
  expect(links).toEqual(["/admin/agents"]);
});

test("shows Decision Models to an LLM manager", () => {
  const links = buildItems([Permission.MANAGE_LLMS], flags, null).map(
    (item) => item.link
  );
  expect(links).toContain("/admin/decision-models");
});

test("marks only Decision Models as a beta entry", () => {
  const betaLinks = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    flags,
    null
  )
    .filter((item) => item.beta)
    .map((item) => item.link);
  expect(betaLinks).toEqual(["/admin/decision-models"]);
});

test("Agents & Plugins holds Agents, Skills and Integrations, with Craft off too", () => {
  const links = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    { ...flags, craftAvailable: false },
    null
  )
    .filter((item) => item.sectionId === "agentsAndPlugins")
    .map((item) => item.link);
  expect(links).toEqual([
    "/admin/agents",
    "/admin/skills",
    "/admin/integrations",
  ]);
});

test("has no MCP Actions, OpenAPI Actions or Craft Apps entries", () => {
  const links = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    { ...flags, craftAvailable: true },
    null
  ).map((item) => item.link);
  expect(links).not.toContain("/admin/mcp-actions");
  expect(links).not.toContain("/admin/openapi-actions");
  expect(links).not.toContain("/admin/craft/apps");
});

test("Channels holds the Slack and Discord bots", () => {
  const items = buildItems(
    [Permission.FULL_ADMIN_PANEL_ACCESS],
    { ...flags, tier: Tier.ENTERPRISE, hooksEnabled: true },
    null
  );
  const section = (link: string) =>
    items.find((item) => item.link === link)?.sectionId;
  expect(
    items
      .filter((item) => item.sectionId === "channels")
      .map((item) => item.nameId)
  ).toEqual(["slackBot", "discordBot"]);
  expect(section("/admin/service-accounts")).toBe("permissions");
  expect(section("/admin/hooks")).toBe("organization");
});

test.each(["/admin/integrations", "/admin/integrations/7"])(
  "gates %s with action management permission",
  (pathname) => {
    expect(matchAdminRoute(pathname)?.requiredPermission).toBe(
      Permission.MANAGE_ACTIONS
    );
  }
);

test("shows Skills only to full admins when Craft is available", () => {
  const craftFlags = { ...flags, craftAvailable: true };
  expect(
    buildItems([Permission.FULL_ADMIN_PANEL_ACCESS], craftFlags, null).map(
      (item) => item.link
    )
  ).toContain("/admin/skills");
  expect(
    buildItems([Permission.MANAGE_PLUGINS], craftFlags, null).map(
      (item) => item.link
    )
  ).not.toContain("/admin/skills");
});
