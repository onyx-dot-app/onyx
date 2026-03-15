import { describe, it, expect } from "vitest";
import { z } from "zod";
import { validateAndTransform } from "./validator";
import { defineComponent } from "../component";
import { createLibrary } from "../library";
import type { ASTNode, ComponentNode, Library } from "../types";

// ── Test library setup ──

const ButtonDef = defineComponent({
  name: "Button",
  description: "A clickable button",
  props: z.object({
    label: z.string(),
    variant: z.enum(["primary", "secondary"]).optional(),
  }),
  component: null,
});

const TextDef = defineComponent({
  name: "Text",
  description: "A text element",
  props: z.object({
    children: z.string(),
  }),
  component: null,
});

const CardDef = defineComponent({
  name: "Card",
  description: "A card container",
  props: z.object({
    title: z.string(),
    subtitle: z.string().optional(),
  }),
  component: null,
});

const InputDef = defineComponent({
  name: "Input",
  description: "A text input",
  props: z.object({
    placeholder: z.string().optional(),
    disabled: z.boolean().optional(),
  }),
  component: null,
});

const EmptyDef = defineComponent({
  name: "Divider",
  description: "A divider with no props",
  props: z.object({}),
  component: null,
});

function makeLibrary(): Library {
  return createLibrary([ButtonDef, TextDef, CardDef, InputDef, EmptyDef]);
}

// ── Helpers for building AST nodes ──

function lit(value: string | number | boolean | null): ASTNode {
  return { kind: "literal", value };
}

function comp(
  name: string,
  args: { key: string | null; value: ASTNode }[],
): ComponentNode {
  return { kind: "component", name, args };
}

function ref(name: string): ASTNode {
  return { kind: "reference", name };
}

function arr(elements: ASTNode[]): ASTNode {
  return { kind: "array", elements };
}

function obj(entries: { key: string; value: ASTNode }[]): ASTNode {
  return { kind: "object", entries };
}

// ── Tests ──

describe("validateAndTransform", () => {
  const library = makeLibrary();

  describe("positional argument mapping", () => {
    it("maps first positional arg to first prop", () => {
      const node = comp("Button", [{ key: null, value: lit("Click me") }]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(element!.component).toBe("Button");
      expect(element!.props.label).toBe("Click me");
      // variant is optional so no validation error for missing it
      expect(errors).toHaveLength(0);
    });

    it("maps second positional arg to second prop", () => {
      const node = comp("Button", [
        { key: null, value: lit("Click me") },
        { key: null, value: lit("secondary") },
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element!.props.label).toBe("Click me");
      expect(element!.props.variant).toBe("secondary");
      expect(errors).toHaveLength(0);
    });

    it("maps multiple positional args in order for Card", () => {
      const node = comp("Card", [
        { key: null, value: lit("My Title") },
        { key: null, value: lit("My Subtitle") },
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element!.props.title).toBe("My Title");
      expect(element!.props.subtitle).toBe("My Subtitle");
      expect(errors).toHaveLength(0);
    });
  });

  describe("named arguments", () => {
    it("passes named args through correctly", () => {
      const node = comp("Button", [
        { key: "label", value: lit("OK") },
        { key: "variant", value: lit("primary") },
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element!.props.label).toBe("OK");
      expect(element!.props.variant).toBe("primary");
      expect(errors).toHaveLength(0);
    });

    it("handles named args in any order", () => {
      const node = comp("Button", [
        { key: "variant", value: lit("secondary") },
        { key: "label", value: lit("Cancel") },
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element!.props.label).toBe("Cancel");
      expect(element!.props.variant).toBe("secondary");
      expect(errors).toHaveLength(0);
    });
  });

  describe("mixed positional + named arguments", () => {
    it("maps positional first then named", () => {
      const node = comp("Button", [
        { key: null, value: lit("Submit") },
        { key: "variant", value: lit("primary") },
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element!.props.label).toBe("Submit");
      expect(element!.props.variant).toBe("primary");
      expect(errors).toHaveLength(0);
    });
  });

  describe("unknown component", () => {
    it("produces error but still returns element", () => {
      const node = comp("Nonexistent", [{ key: null, value: lit("hello") }]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(element!.component).toBe("Nonexistent");
      expect(errors).toHaveLength(1);
      expect(errors[0]!.message).toContain('Unknown component: "Nonexistent"');
    });

    it("still assigns positional args as generic props for unknown component", () => {
      // Unknown component has no paramDefs, so all positional args become children
      const node = comp("Foo", [
        { key: null, value: comp("Button", [{ key: null, value: lit("hi") }]) },
      ]);
      const { element } = validateAndTransform(node, library);

      // The positional arg should become a child since there are no param defs
      expect(element!.children).toHaveLength(1);
      expect(element!.children[0]!.component).toBe("Button");
    });

    it("passes named args through even for unknown component", () => {
      const node = comp("Unknown", [{ key: "title", value: lit("hey") }]);
      const { element } = validateAndTransform(node, library);

      expect(element!.props.title).toBe("hey");
    });
  });

  describe("literal string wrapping", () => {
    it("wraps a literal string in a Text element", () => {
      const node = lit("Hello world");
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(element!.component).toBe("Text");
      expect(element!.props.children).toBe("Hello world");
      expect(element!.children).toHaveLength(0);
      expect(errors).toHaveLength(0);
    });

    it("returns null for non-string literals", () => {
      const numNode = lit(42);
      expect(validateAndTransform(numNode, library).element).toBeNull();

      const boolNode = lit(true);
      expect(validateAndTransform(boolNode, library).element).toBeNull();

      const nullNode = lit(null);
      expect(validateAndTransform(nullNode, library).element).toBeNull();
    });
  });

  describe("array wrapping", () => {
    it("wraps array in a Stack element", () => {
      const node = arr([
        comp("Button", [{ key: null, value: lit("A") }]),
        comp("Button", [{ key: null, value: lit("B") }]),
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(element!.component).toBe("Stack");
      expect(element!.children).toHaveLength(2);
      expect(element!.children[0]!.component).toBe("Button");
      expect(element!.children[1]!.component).toBe("Button");
      expect(errors).toHaveLength(0);
    });

    it("filters out null elements from array children", () => {
      // A number literal returns null from transformNode
      const node = arr([
        comp("Button", [{ key: null, value: lit("OK") }]),
        lit(42),
      ]);
      const { element } = validateAndTransform(node, library);

      expect(element!.component).toBe("Stack");
      expect(element!.children).toHaveLength(1);
    });

    it("wraps empty array as empty Stack", () => {
      const node = arr([]);
      const { element } = validateAndTransform(node, library);

      expect(element!.component).toBe("Stack");
      expect(element!.children).toHaveLength(0);
    });
  });

  describe("object literal", () => {
    it("produces error and returns null", () => {
      const node = obj([{ key: "a", value: lit("b") }]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).toBeNull();
      expect(errors).toHaveLength(1);
      expect(errors[0]!.message).toContain("Object literal cannot be rendered");
    });
  });

  describe("unresolved reference", () => {
    it("produces __Unresolved placeholder", () => {
      const node = ref("someVar");
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(element!.component).toBe("__Unresolved");
      expect(element!.props.name).toBe("someVar");
      expect(element!.children).toHaveLength(0);
      expect(errors).toHaveLength(0);
    });
  });

  describe("nested components", () => {
    it("handles component as a named arg value", () => {
      // Card with title as a string, but imagine a prop that accepts a component
      // Since the validator calls astToValue for component nodes, it returns an ElementNode
      const innerButton = comp("Button", [{ key: null, value: lit("Inner") }]);
      const node = comp("Card", [{ key: "title", value: innerButton }]);
      const { element } = validateAndTransform(node, library);

      // The inner button becomes an ElementNode object in props
      expect(element!.props.title).toEqual({
        kind: "element",
        component: "Button",
        props: { label: "Inner" },
        children: [],
      });
    });

    it("handles component as positional arg", () => {
      const innerText = comp("Text", [{ key: null, value: lit("hello") }]);
      const node = comp("Card", [{ key: null, value: innerText }]);
      const { element } = validateAndTransform(node, library);

      // First positional maps to "title" param — value is the ElementNode
      expect(element!.props.title).toEqual(
        expect.objectContaining({ kind: "element", component: "Text" }),
      );
    });
  });

  describe("Zod validation errors", () => {
    it("reports error when required prop is missing", () => {
      // Button requires label (z.string()), pass no args
      const node = comp("Button", []);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull(); // still returns the element
      expect(element!.component).toBe("Button");
      expect(errors.length).toBeGreaterThan(0);
      expect(errors.some((e) => e.message.includes("Button"))).toBe(true);
    });

    it("reports error for wrong type", () => {
      // Button label expects string, pass a number
      const node = comp("Button", [{ key: null, value: lit(42) }]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(errors.length).toBeGreaterThan(0);
      expect(errors.some((e) => e.message.includes("label"))).toBe(true);
    });

    it("reports error for invalid enum value", () => {
      const node = comp("Button", [
        { key: null, value: lit("OK") },
        { key: null, value: lit("invalid-variant") },
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(errors.length).toBeGreaterThan(0);
      expect(errors.some((e) => e.message.includes("variant"))).toBe(true);
    });

    it("reports error for wrong boolean type", () => {
      // Input.disabled expects boolean, pass a string
      const node = comp("Input", [{ key: "disabled", value: lit("yes") }]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(errors.length).toBeGreaterThan(0);
      expect(errors.some((e) => e.message.includes("disabled"))).toBe(true);
    });
  });

  describe("extra positional args beyond param count", () => {
    it("treats extra positional args as children", () => {
      // Button has 2 params (label, variant). Third positional should become a child.
      const extraChild = comp("Text", [{ key: null, value: lit("extra") }]);
      const node = comp("Button", [
        { key: null, value: lit("Click") },
        { key: null, value: lit("primary") },
        { key: null, value: extraChild },
      ]);
      const { element } = validateAndTransform(node, library);

      expect(element!.children).toHaveLength(1);
      expect(element!.children[0]!.component).toBe("Text");
    });

    it("handles multiple extra positional args as children", () => {
      const child1 = comp("Button", [{ key: null, value: lit("A") }]);
      const child2 = comp("Button", [{ key: null, value: lit("B") }]);
      const node = comp("Button", [
        { key: null, value: lit("Parent") },
        { key: null, value: lit("primary") },
        { key: null, value: child1 },
        { key: null, value: child2 },
      ]);
      const { element } = validateAndTransform(node, library);

      expect(element!.children).toHaveLength(2);
    });

    it("skips null children from extra positional args", () => {
      // A number literal transforms to null, so it should be filtered out
      const node = comp("Button", [
        { key: null, value: lit("Click") },
        { key: null, value: lit("primary") },
        { key: null, value: lit(999) }, // number literal → null child
      ]);
      const { element } = validateAndTransform(node, library);

      expect(element!.children).toHaveLength(0);
    });
  });

  describe("component with no args", () => {
    it("renders component with empty props and no errors when all props are optional", () => {
      const node = comp("Input", []);
      const { element, errors } = validateAndTransform(node, library);

      expect(element).not.toBeNull();
      expect(element!.component).toBe("Input");
      expect(element!.props).toEqual({});
      expect(element!.children).toHaveLength(0);
      expect(errors).toHaveLength(0);
    });

    it("renders component with empty props and no children for empty schema", () => {
      const node = comp("Divider", []);
      const { element, errors } = validateAndTransform(node, library);

      expect(element!.component).toBe("Divider");
      expect(element!.props).toEqual({});
      expect(errors).toHaveLength(0);
    });
  });

  describe("astToValue edge cases", () => {
    it("converts array prop values with nested components", () => {
      // Pass an array as a named prop — components inside become ElementNodes
      const node = comp("Card", [
        {
          key: "title",
          value: arr([comp("Button", [{ key: null, value: lit("A") }])]),
        },
      ]);
      const { element } = validateAndTransform(node, library);

      const titleProp = element!.props.title as unknown[];
      expect(Array.isArray(titleProp)).toBe(true);
      expect(titleProp[0]).toEqual(
        expect.objectContaining({ kind: "element", component: "Button" }),
      );
    });

    it("converts object prop values to plain objects", () => {
      const node = comp("Card", [
        {
          key: "title",
          value: obj([
            { key: "text", value: lit("hello") },
            { key: "bold", value: lit(true) },
          ]),
        },
      ]);
      const { element } = validateAndTransform(node, library);

      expect(element!.props.title).toEqual({ text: "hello", bold: true });
    });

    it("converts reference in prop to { __ref: name } placeholder", () => {
      const node = comp("Card", [{ key: "title", value: ref("myVar") }]);
      const { element } = validateAndTransform(node, library);

      expect(element!.props.title).toEqual({ __ref: "myVar" });
    });

    it("converts literal prop values directly", () => {
      const node = comp("Input", [
        { key: "placeholder", value: lit("Type here") },
        { key: "disabled", value: lit(false) },
      ]);
      const { element, errors } = validateAndTransform(node, library);

      expect(element!.props.placeholder).toBe("Type here");
      expect(element!.props.disabled).toBe(false);
      expect(errors).toHaveLength(0);
    });
  });
});
