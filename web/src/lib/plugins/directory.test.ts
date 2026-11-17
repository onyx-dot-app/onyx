import { memberPluginEntries } from "@/lib/plugins/directory";
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
