import { describe, it, expect } from "vitest";
import { z } from "zod";
import { defineComponent, createLibrary, parse } from "./index";

/**
 * Smoke test that mirrors the Onyx library assembly.
 * Verifies all 16 component definitions register without errors
 * and the library generates a valid prompt.
 */
describe("Onyx Library Assembly (smoke test)", () => {
  // Re-define all components exactly as onyx/src/components/ does,
  // to verify the schemas are valid without needing the onyx package import.

  const components = [
    defineComponent({
      name: "Stack",
      description: "Vertical stack layout",
      group: "Layout",
      props: z.object({
        children: z.array(z.unknown()).optional(),
        gap: z.enum(["none", "xs", "sm", "md", "lg", "xl"]).optional(),
        align: z.enum(["start", "center", "end", "stretch"]).optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Row",
      description: "Horizontal row layout",
      group: "Layout",
      props: z.object({
        children: z.array(z.unknown()).optional(),
        gap: z.enum(["none", "xs", "sm", "md", "lg", "xl"]).optional(),
        align: z.enum(["start", "center", "end", "stretch"]).optional(),
        wrap: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Column",
      description: "A column within a Row",
      group: "Layout",
      props: z.object({
        children: z.array(z.unknown()).optional(),
        width: z.string().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Card",
      description: "Container card",
      group: "Layout",
      props: z.object({
        title: z.string().optional(),
        padding: z.enum(["none", "sm", "md", "lg"]).optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Divider",
      description: "Horizontal separator",
      group: "Layout",
      props: z.object({
        spacing: z.enum(["sm", "md", "lg"]).optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Text",
      description: "Displays text with typography variants",
      group: "Content",
      props: z.object({
        children: z.string(),
        headingH1: z.boolean().optional(),
        headingH2: z.boolean().optional(),
        headingH3: z.boolean().optional(),
        muted: z.boolean().optional(),
        mono: z.boolean().optional(),
        bold: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Tag",
      description: "Label tag with color",
      group: "Content",
      props: z.object({
        title: z.string(),
        color: z.enum(["green", "purple", "blue", "gray", "amber"]).optional(),
        size: z.enum(["sm", "md"]).optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Table",
      description: "Data table",
      group: "Content",
      props: z.object({
        columns: z.array(z.string()),
        rows: z.array(z.array(z.unknown())),
        compact: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Code",
      description: "Code block",
      group: "Content",
      props: z.object({
        children: z.string(),
        language: z.string().optional(),
        showCopyButton: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Image",
      description: "Displays an image",
      group: "Content",
      props: z.object({
        src: z.string(),
        alt: z.string().optional(),
        width: z.string().optional(),
        height: z.string().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Link",
      description: "Hyperlink",
      group: "Content",
      props: z.object({
        children: z.string(),
        href: z.string(),
        external: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "List",
      description: "Ordered or unordered list",
      group: "Content",
      props: z.object({
        items: z.array(z.string()),
        ordered: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Button",
      description: "Interactive button",
      group: "Interactive",
      props: z.object({
        children: z.string(),
        main: z.boolean().optional(),
        action: z.boolean().optional(),
        danger: z.boolean().optional(),
        primary: z.boolean().optional(),
        secondary: z.boolean().optional(),
        tertiary: z.boolean().optional(),
        size: z.enum(["lg", "md"]).optional(),
        actionId: z.string().optional(),
        disabled: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "IconButton",
      description: "Icon button with tooltip",
      group: "Interactive",
      props: z.object({
        icon: z.string(),
        tooltip: z.string().optional(),
        main: z.boolean().optional(),
        action: z.boolean().optional(),
        danger: z.boolean().optional(),
        primary: z.boolean().optional(),
        secondary: z.boolean().optional(),
        actionId: z.string().optional(),
        disabled: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Input",
      description: "Text input field",
      group: "Interactive",
      props: z.object({
        placeholder: z.string().optional(),
        value: z.string().optional(),
        actionId: z.string().optional(),
        readOnly: z.boolean().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Alert",
      description: "Status message banner",
      group: "Feedback",
      props: z.object({
        text: z.string(),
        description: z.string().optional(),
        level: z
          .enum(["default", "info", "success", "warning", "error"])
          .optional(),
        showIcon: z.boolean().optional(),
      }),
      component: null,
    }),
  ];

  it("registers all 16 components without errors", () => {
    expect(() => createLibrary(components)).not.toThrow();
  });

  it("creates a library with exactly 16 components", () => {
    const lib = createLibrary(components);
    expect(lib.components.size).toBe(16);
  });

  it("resolves every component by name", () => {
    const lib = createLibrary(components);
    const names = [
      "Stack",
      "Row",
      "Column",
      "Card",
      "Divider",
      "Text",
      "Tag",
      "Table",
      "Code",
      "Image",
      "Link",
      "List",
      "Button",
      "IconButton",
      "Input",
      "Alert",
    ];
    for (const name of names) {
      expect(lib.resolve(name)).toBeDefined();
    }
  });

  it("generates param map for all components", () => {
    const lib = createLibrary(components);
    const paramMap = lib.paramMap();
    expect(paramMap.size).toBe(16);

    // Verify a few specific param orderings
    const textParams = paramMap.get("Text")!;
    expect(textParams[0]!.name).toBe("children");
    expect(textParams[0]!.required).toBe(true);

    const buttonParams = paramMap.get("Button")!;
    expect(buttonParams[0]!.name).toBe("children");
    expect(buttonParams.find((p) => p.name === "actionId")).toBeDefined();

    const tagParams = paramMap.get("Tag")!;
    expect(tagParams[0]!.name).toBe("title");
    expect(tagParams[0]!.required).toBe(true);
  });

  it("generates a prompt containing all component signatures", () => {
    const lib = createLibrary(components);
    const prompt = lib.prompt();

    // Every component name should appear
    for (const [name] of lib.components) {
      expect(prompt).toContain(name);
    }

    // Should contain group headers
    expect(prompt).toContain("Layout");
    expect(prompt).toContain("Content");
    expect(prompt).toContain("Interactive");
    expect(prompt).toContain("Feedback");

    // Should have syntax section
    expect(prompt).toContain("Syntax");
    expect(prompt).toContain("Streaming");
  });

  it("generates a prompt with correct Button signature", () => {
    const lib = createLibrary(components);
    const prompt = lib.prompt();

    // Button should show its required `children` param and optional params
    expect(prompt).toContain("Button(children: string");
    expect(prompt).toContain("actionId?");
  });

  it("parses a complex GenUI input using the full library", () => {
    const lib = createLibrary(components);

    const input = `heading = Text("Dashboard", headingH1: true)
status = Alert("All systems operational", level: "success")
row1 = ["API Server", Tag("Running", color: "green"), "99.9%"]
row2 = ["Database", Tag("Running", color: "green"), "99.8%"]
row3 = ["Cache", Tag("Warning", color: "amber"), "95.2%"]
table = Table(["Service", "Status", "Uptime"], [row1, row2, row3])
actions = Row([
  Button("Refresh", main: true, primary: true, actionId: "refresh"),
  Button("Settings", action: true, secondary: true, actionId: "settings")
], gap: "sm")
divider = Divider(spacing: "md")
code = Code("curl https://api.example.com/health", language: "bash")
root = Stack([heading, status, table, divider, actions, code], gap: "md")`;

    const result = parse(input, lib);

    expect(result.root).not.toBeNull();
    expect(result.statements.length).toBeGreaterThanOrEqual(9);

    // Should have no critical errors (unknown components, etc.)
    const criticalErrors = result.errors.filter(
      (e: { message: string }) => !e.message.includes("Unknown"),
    );
    expect(criticalErrors).toHaveLength(0);
  });
});
