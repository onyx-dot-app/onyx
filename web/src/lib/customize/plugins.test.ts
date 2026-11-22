import { groupPlugins } from "@/lib/customize/plugins";
import type { MemberPluginEntry } from "@/lib/plugins/directory";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

const ME = "me@example.com";

function entry(over: Partial<MemberPluginEntry>): MemberPluginEntry {
  return {
    id: "plugin",
    name: "plugin",
    description: null,
    section: "shared",
    ownerEmail: null,
    marketplace: null,
    skills: [customFixture({ enabled: true })],
    ...over,
  };
}

const ENTRIES = [
  entry({ id: "mine-published", section: "organization", ownerEmail: ME }),
  entry({
    id: "org",
    section: "organization",
    ownerEmail: "admin@example.com",
  }),
  entry({ id: "shared", section: "shared", ownerEmail: "other@example.com" }),
  entry({ id: "synced", section: "marketplace", ownerEmail: ME }),
  entry({ id: "private", section: "private", ownerEmail: "other@example.com" }),
  entry({
    id: "off",
    name: "reports",
    section: "shared",
    ownerEmail: "other@example.com",
    skills: [customFixture({ enabled: false })],
  }),
];

function ids(options: { status?: "all" | "on" | "off"; query?: string } = {}) {
  const groups = groupPlugins(ENTRIES, {
    userEmail: ME,
    query: options.query ?? "",
    status: options.status ?? "all",
    locale: "en",
  });
  return {
    mine: groups.mine.map((plugin) => plugin.id),
    organization: groups.organization.map((plugin) => plugin.id),
    shared: groups.shared.map((plugin) => plugin.id),
    marketplace: groups.marketplace.map((plugin) => plugin.id),
    private: groups.private.map((plugin) => plugin.id),
  };
}

test("the user's own plugins stay in Created by you after a publish", () => {
  expect(ids()).toEqual({
    mine: ["mine-published"],
    organization: ["org"],
    shared: ["shared", "off"],
    marketplace: ["synced"],
    private: ["private"],
  });
});

test("the status filter follows the switch and the search matches names", () => {
  expect(ids({ status: "off" }).shared).toEqual(["off"]);
  expect(ids({ query: "REPORTS" })).toEqual({
    mine: [],
    organization: [],
    shared: ["off"],
    marketplace: [],
    private: [],
  });
});
