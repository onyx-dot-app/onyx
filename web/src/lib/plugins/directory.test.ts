import { memberPluginEntries, pluginSwitch } from "@/lib/plugins/directory";
import { customFixture } from "@/lib/skills/__fixtures__/picker";

const skill = customFixture({
  id: "33333333-3333-4333-8333-333333333333",
  name: "report-writer",
  owner: { id: "u1", email: "me@example.com" },
});

test("each custom skill is one plugin, in its section", () => {
  const entries = memberPluginEntries(
    [
      skill,
      { ...skill, source: "builtin", id: "builtin" },
      {
        ...skill,
        id: "44444444-4444-4444-8444-444444444444",
        name: "audit",
        owner: { id: "u2", email: "other@example.com" },
      },
    ],
    "me@example.com",
    "en"
  );
  expect(entries.map(({ name, section }) => ({ name, section }))).toEqual([
    { name: "audit", section: "shared" },
    { name: "report-writer", section: "mine" },
  ]);
});

test("the switch of a plugin follows its skill", () => {
  const [entry] = memberPluginEntries(
    [{ ...skill, enabled: true, can_toggle: false, required_for_user: true }],
    null,
    "en"
  );
  if (!entry) throw new Error("No entry");
  expect(pluginSwitch(entry)).toEqual({ enabled: true, blocked: "required" });
});
