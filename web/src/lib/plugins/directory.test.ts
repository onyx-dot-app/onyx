import {
  memberPluginEntries,
  ownsPrivateIntegrationPlugin,
  pluginSwitch,
} from "@/lib/plugins/directory";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import {
  LINEAR_PLUGIN_ID,
  makeMemberIntegration,
} from "@/sections/plugins/__tests__/memberIntegrationFixtures";

const skill = customFixture({
  id: "33333333-3333-4333-8333-333333333333",
  name: "report-writer",
  owner: { id: "u1", email: "me@example.com" },
});
const linear = makeMemberIntegration();
const personal = makeMemberIntegration({
  id: 2,
  name: "Reports API",
  description: "Weekly reports",
  status: { state: "connected", reason: null },
  plugins: [
    {
      plugin_id: "44444444-4444-4444-8444-444444444444",
      plugin_name: "Reports",
      scope: "personal",
      owner_email: "me@example.com",
      installation_policy: null,
      enabled: true,
    },
  ],
});

test("joins custom skills and integration plugins by plugin id", () => {
  const entries = memberPluginEntries(
    [skill, { ...skill, source: "builtin", id: "builtin" }],
    [linear, personal],
    "me@example.com",
    "en"
  );
  expect(
    entries.map(({ name, section, skills, integrations }) => ({
      name,
      section,
      skills: skills.length,
      integrations: integrations.length,
    }))
  ).toEqual([
    { name: "Linear", section: "organization", skills: 0, integrations: 1 },
    { name: "report-writer", section: "mine", skills: 1, integrations: 0 },
    { name: "Reports", section: "mine", skills: 0, integrations: 1 },
  ]);
});

test("a plugin that holds a skill and an integration is one entry", () => {
  const entries = memberPluginEntries(
    [{ ...skill, id: LINEAR_PLUGIN_ID }],
    [linear],
    null,
    "en"
  );
  expect(entries).toHaveLength(1);
  expect(entries[0]?.skills).toHaveLength(1);
  expect(entries[0]?.integrations).toEqual([linear]);
});

test("the switch of an integration plugin follows its ref", () => {
  const [entry] = memberPluginEntries([], [linear], null, "en");
  if (!entry) throw new Error("No entry");
  expect(pluginSwitch(entry)).toEqual({ enabled: true, blocked: null });
  const required = {
    ...entry,
    ref: entry.ref && {
      ...entry.ref,
      installation_policy: "REQUIRED" as const,
    },
  };
  expect(pluginSwitch(required).blocked).toBe("required");
});

test("only the owner of a private integration plugin shares it", () => {
  const entries = memberPluginEntries([], [linear, personal], null, "en");
  const reports = entries.find((entry) => entry.name === "Reports");
  const organization = entries.find((entry) => entry.name === "Linear");
  if (!reports || !organization) throw new Error("No entry");
  expect(ownsPrivateIntegrationPlugin(reports, "me@example.com")).toBe(true);
  expect(ownsPrivateIntegrationPlugin(reports, "other@example.com")).toBe(
    false
  );
  expect(ownsPrivateIntegrationPlugin(organization, "me@example.com")).toBe(
    false
  );
});
