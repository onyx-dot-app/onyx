import { groupSkills, type SkillListOptions } from "@/lib/customize/skills";
import {
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";
import type { SkillsList } from "@/lib/skills/types";

const ME = "user-me";

const OPTIONS: SkillListOptions = {
  userId: ME,
  craftEnabled: true,
  query: "",
  status: "all",
  sort: "name",
  locale: "en",
};

const LIST: SkillsList = {
  builtins: [
    builtinFixture({ id: "pptx", name: "pptx" }),
    {
      ...builtinFixture({ id: "hidden", name: "browser" }),
      is_available: null,
    },
  ],
  customs: [
    customFixture({
      id: "mine",
      name: "notes",
      owner: { id: ME, email: "me@example.com" },
      published_version_number: 2,
    }),
    customFixture({
      id: "org",
      name: "weekly-report",
      owner: { id: "other", email: "other@example.com" },
      published_version_number: 1,
      enabled: false,
    }),
    customFixture({
      id: "shared",
      name: "release-notes",
      owner: { id: "other", email: "other@example.com" },
      published_version_number: null,
    }),
  ],
};

function ids(options: Partial<SkillListOptions> = {}) {
  const groups = groupSkills(LIST, { ...OPTIONS, ...options });
  return {
    mine: groups.mine.map((skill) => skill.id),
    organization: groups.organization.map((skill) => skill.id),
    shared: groups.shared.map((skill) => skill.id),
    builtin: groups.builtin.map((skill) => skill.id),
  };
}

test("groups by owner first, then by publish state", () => {
  expect(ids()).toEqual({
    mine: ["mine"],
    organization: ["org"],
    shared: ["shared"],
    builtin: ["pptx"],
  });
});

test("with Craft off, built-in skills are hidden as in chat", () => {
  expect(ids({ craftEnabled: false }).builtin).toEqual([]);
});

test("the status filter and the search narrow every group", () => {
  expect(ids({ status: "off" })).toEqual({
    mine: [],
    organization: ["org"],
    shared: [],
    builtin: [],
  });
  expect(ids({ query: "RELEASE" }).shared).toEqual(["shared"]);
  expect(ids({ query: "RELEASE" }).organization).toEqual([]);
});

test("a skill synced from a marketplace is grouped by its marketplace, not its owner", () => {
  const groups = groupSkills(
    {
      builtins: [],
      customs: [
        customFixture({
          id: "synced",
          name: "frontend-design",
          owner: { id: ME, email: "me@example.com" },
          marketplace: {
            id: "m1",
            name: "claude-code-plugins",
            kind: "github",
            repository: "anthropics/claude-code",
            personal: true,
          },
        }),
      ],
    },
    OPTIONS
  );
  expect(groups.mine).toEqual([]);
  expect(groups.marketplace.map((skill) => skill.id)).toEqual(["synced"]);
});
