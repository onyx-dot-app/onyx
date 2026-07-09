import {
  detectSlashTrigger,
  filterPickerSections,
  flattenSections,
  toPickerSections,
  type PickerSections,
} from "@/lib/skills/picker";
import {
  appFixture,
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";
import type { SkillsList } from "@/lib/skills/types";

describe("detectSlashTrigger", () => {
  it("returns null when no slash present", () => {
    expect(detectSlashTrigger("hello world")).toBeNull();
  });

  it("matches a leading slash with empty query", () => {
    expect(detectSlashTrigger("/")).toEqual({ slashIndex: 0, query: "" });
  });

  it("matches a leading slash with a query", () => {
    expect(detectSlashTrigger("/sla")).toEqual({ slashIndex: 0, query: "sla" });
  });

  it("matches a slash after whitespace", () => {
    expect(detectSlashTrigger("hello /sl")).toEqual({
      slashIndex: 6,
      query: "sl",
    });
  });

  it("rejects a slash not preceded by whitespace", () => {
    expect(detectSlashTrigger("http://x")).toBeNull();
  });

  it("rejects when query contains whitespace", () => {
    expect(detectSlashTrigger("/foo bar")).toBeNull();
  });
});

describe("toPickerSections", () => {
  function skillsList(over: Partial<SkillsList> = {}): SkillsList {
    return { builtins: [], customs: [], ...over };
  }

  it("returns empty sections when no data", () => {
    expect(toPickerSections(undefined, undefined)).toEqual({
      skills: [],
      apps: [],
    });
  });

  it("places plain built-ins in `skills`", () => {
    const data = skillsList({
      builtins: [
        builtinFixture({ slug: "pptx" }),
        builtinFixture({ slug: "image-gen" }),
      ],
    });
    const result = toPickerSections(data, []);
    expect(result.skills.map((s) => s.slug)).toEqual(["image-gen", "pptx"]);
    expect(result.apps).toEqual([]);
  });

  it("filters out unavailable built-ins", () => {
    const data = skillsList({
      builtins: [
        builtinFixture({ slug: "pptx" }),
        builtinFixture({ slug: "image-gen", is_available: false }),
      ],
    });
    expect(toPickerSections(data, []).skills.map((s) => s.slug)).toEqual([
      "pptx",
    ]);
  });

  it("appends enabled customs to `skills`", () => {
    const data = skillsList({
      builtins: [builtinFixture({ slug: "pptx" })],
      customs: [
        customFixture({ slug: "my-custom" }),
        customFixture({ slug: "disabled-one", enabled: false }),
      ],
    });
    expect(toPickerSections(data, []).skills.map((s) => s.slug)).toEqual([
      "my-custom",
      "pptx",
    ]);
  });

  it("builds the Apps section from the external-apps payload with auth state", () => {
    const data = skillsList({ builtins: [builtinFixture({ slug: "pptx" })] });
    const apps = [
      appFixture({ slug: "slack", app_type: "SLACK", authenticated: true }),
      appFixture({
        slug: "gmail",
        name: "Gmail",
        app_type: "GMAIL",
        authenticated: false,
      }),
    ];
    const { apps: result } = toPickerSections(data, apps);
    expect(result.map((a) => [a.slug, a.name, a.authenticated])).toEqual([
      ["gmail", "Gmail", false],
      ["slack", "slack", true],
    ]);
  });

  it("returns an empty Apps section when the user has no apps", () => {
    expect(toPickerSections(skillsList(), []).apps).toEqual([]);
  });

  it("returns Apps even when skills payload is undefined", () => {
    const apps = [appFixture({ slug: "slack", app_type: "SLACK" })];
    const result = toPickerSections(undefined, apps);
    expect(result.skills).toEqual([]);
    expect(result.apps.map((a) => a.slug)).toEqual(["slack"]);
  });
});

describe("filterPickerSections", () => {
  const sections: PickerSections = {
    skills: [
      {
        kind: "skill",
        slug: "pptx",
        name: "PPTX",
        description: "build decks",
      },
      {
        kind: "skill",
        slug: "image-gen",
        name: "Image Gen",
        description: "make images",
      },
    ],
    apps: [
      {
        kind: "app",
        slug: "slack",
        name: "Slack",
        description: "chat search",
        appType: "SLACK",
        authenticated: true,
      },
    ],
  };

  it("returns input when query is empty", () => {
    expect(filterPickerSections(sections, "")).toEqual(sections);
  });

  it("filters both sections case-insensitively across fields", () => {
    expect(filterPickerSections(sections, "image").skills.length).toBe(1);
    expect(filterPickerSections(sections, "CHAT").apps.length).toBe(1);
    expect(
      filterPickerSections(sections, "deck").skills.map((s) => s.slug)
    ).toEqual(["pptx"]);
  });

  it("returns empty sections when nothing matches", () => {
    const empty = filterPickerSections(sections, "zzz");
    expect(empty.skills).toEqual([]);
    expect(empty.apps).toEqual([]);
  });
});

describe("flattenSections", () => {
  it("returns skills before apps in render order", () => {
    const sections: PickerSections = {
      skills: [
        { kind: "skill", slug: "a", name: "A", description: "" },
        { kind: "skill", slug: "b", name: "B", description: "" },
      ],
      apps: [
        {
          kind: "app",
          slug: "c",
          name: "C",
          description: "",
          appType: "SLACK",
          authenticated: true,
        },
      ],
    };
    expect(flattenSections(sections).map((e) => e.slug)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });
});
