import { describe, it, expect } from "vitest";
import { z } from "zod";
import { defineComponent, createLibrary, parse } from "./index";

/**
 * Integration tests: end-to-end from source → parsed element tree.
 */

function makeTestLibrary() {
  return createLibrary([
    defineComponent({
      name: "Text",
      description: "Displays text",
      props: z.object({
        children: z.string(),
        headingH2: z.boolean().optional(),
      }),
      component: null,
      group: "Content",
    }),
    defineComponent({
      name: "Button",
      description: "Interactive button",
      props: z.object({
        children: z.string(),
        main: z.boolean().optional(),
        primary: z.boolean().optional(),
        actionId: z.string().optional(),
      }),
      component: null,
      group: "Interactive",
    }),
    defineComponent({
      name: "Tag",
      description: "Label tag",
      props: z.object({
        title: z.string(),
        color: z.enum(["green", "purple", "blue", "gray", "amber"]).optional(),
      }),
      component: null,
      group: "Content",
    }),
    defineComponent({
      name: "Table",
      description: "Data table",
      props: z.object({
        columns: z.array(z.string()),
        rows: z.array(z.array(z.unknown())),
      }),
      component: null,
      group: "Content",
    }),
    defineComponent({
      name: "Stack",
      description: "Vertical layout",
      props: z.object({
        children: z.array(z.unknown()).optional(),
        gap: z.enum(["none", "xs", "sm", "md", "lg", "xl"]).optional(),
      }),
      component: null,
      group: "Layout",
    }),
  ]);
}

describe("Integration: parse()", () => {
  it("parses the spec example end-to-end", () => {
    const lib = makeTestLibrary();
    const input = `title = Text("Search Results", headingH2: true)
row1 = ["Onyx Docs", Tag("PDF", color: "blue"), "2024-01-15"]
row2 = ["API Guide", Tag("MD", color: "green"), "2024-02-01"]
results = Table(["Name", "Type", "Date"], [row1, row2])
action = Button("View All", main: true, primary: true, actionId: "viewAll")
root = Stack([title, results, action], gap: "md")`;

    const result = parse(input, lib);
    expect(result.root).not.toBeNull();
    // Root should be a Stack element
    if (result.root && "component" in result.root) {
      expect((result.root as any).component).toBe("Stack");
    }
  });

  it("parses a single component", () => {
    const lib = makeTestLibrary();
    const result = parse('x = Text("Hello World")', lib);
    expect(result.root).not.toBeNull();
    expect(
      result.errors.filter((e) => !e.message.includes("Unknown")),
    ).toHaveLength(0);
  });

  it("handles unknown components gracefully", () => {
    const lib = makeTestLibrary();
    const result = parse('x = UnknownWidget("test")', lib);
    expect(result.root).not.toBeNull();
    expect(
      result.errors.some((e) => e.message.includes("Unknown component")),
    ).toBe(true);
  });

  it("handles empty input", () => {
    const lib = makeTestLibrary();
    const result = parse("", lib);
    expect(result.root).toBeNull();
    expect(result.errors).toHaveLength(0);
  });
});

describe("Integration: library.prompt()", () => {
  it("generates a prompt with component signatures", () => {
    const lib = makeTestLibrary();
    const prompt = lib.prompt();

    expect(prompt).toContain("GenUI Lang");
    expect(prompt).toContain("Text(");
    expect(prompt).toContain("Button(");
    expect(prompt).toContain("Tag(");
    expect(prompt).toContain("Table(");
    expect(prompt).toContain("Stack(");
  });

  it("includes syntax rules", () => {
    const lib = makeTestLibrary();
    const prompt = lib.prompt();

    expect(prompt).toContain("PascalCase");
    expect(prompt).toContain("camelCase");
    expect(prompt).toContain("positional");
  });

  it("includes streaming guidelines by default", () => {
    const lib = makeTestLibrary();
    const prompt = lib.prompt();

    expect(prompt).toContain("Streaming");
  });

  it("can disable streaming guidelines", () => {
    const lib = makeTestLibrary();
    const prompt = lib.prompt({ streaming: false });

    expect(prompt).not.toContain("Streaming Guidelines");
  });

  it("includes custom examples", () => {
    const lib = makeTestLibrary();
    const prompt = lib.prompt({
      examples: [{ description: "Test example", code: 'x = Text("test")' }],
    });

    expect(prompt).toContain("Test example");
    expect(prompt).toContain('x = Text("test")');
  });
});

describe("Integration: defineComponent", () => {
  it("rejects non-PascalCase names", () => {
    expect(() =>
      defineComponent({
        name: "button",
        description: "Invalid",
        props: z.object({}),
        component: null,
      }),
    ).toThrow("PascalCase");
  });

  it("accepts valid PascalCase names", () => {
    expect(() =>
      defineComponent({
        name: "MyWidget",
        description: "Valid",
        props: z.object({}),
        component: null,
      }),
    ).not.toThrow();
  });
});

describe("Integration: createLibrary", () => {
  it("rejects duplicate component names", () => {
    const comp = defineComponent({
      name: "Foo",
      description: "Foo",
      props: z.object({}),
      component: null,
    });

    expect(() => createLibrary([comp, comp])).toThrow("Duplicate");
  });

  it("resolves components by name", () => {
    const lib = makeTestLibrary();
    expect(lib.resolve("Text")).toBeDefined();
    expect(lib.resolve("NonExistent")).toBeUndefined();
  });

  it("generates param map", () => {
    const lib = makeTestLibrary();
    const paramMap = lib.paramMap();

    const textParams = paramMap.get("Text");
    expect(textParams).toBeDefined();
    expect(textParams![0]!.name).toBe("children");
    expect(textParams![0]!.required).toBe(true);
  });
});
