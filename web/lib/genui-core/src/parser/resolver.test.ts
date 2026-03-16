import { describe, it, expect } from "vitest";
import { resolveReferences } from "./resolver";
import type { Statement } from "../types";

describe("resolveReferences", () => {
  it("resolves simple variable references", () => {
    const statements: Statement[] = [
      { name: "a", value: { kind: "literal", value: "hello" } },
      { name: "b", value: { kind: "reference", name: "a" } },
    ];

    const { resolved, errors } = resolveReferences(statements);
    expect(errors).toHaveLength(0);
    expect(resolved.get("b")).toEqual({ kind: "literal", value: "hello" });
  });

  it("resolves nested references in components", () => {
    const statements: Statement[] = [
      { name: "label", value: { kind: "literal", value: "Click me" } },
      {
        name: "btn",
        value: {
          kind: "component",
          name: "Button",
          args: [{ key: null, value: { kind: "reference", name: "label" } }],
        },
      },
    ];

    const { resolved, errors } = resolveReferences(statements);
    expect(errors).toHaveLength(0);
    const btn = resolved.get("btn");
    expect(btn?.kind).toBe("component");
    if (btn?.kind === "component") {
      expect(btn.args[0]!.value).toEqual({
        kind: "literal",
        value: "Click me",
      });
    }
  });

  it("detects circular references", () => {
    const statements: Statement[] = [
      { name: "a", value: { kind: "reference", name: "b" } },
      { name: "b", value: { kind: "reference", name: "a" } },
    ];

    const { errors } = resolveReferences(statements);
    expect(errors.some((e) => e.message.includes("Circular"))).toBe(true);
  });

  it("leaves unknown references as-is", () => {
    const statements: Statement[] = [
      { name: "x", value: { kind: "reference", name: "unknown" } },
    ];

    const { resolved, errors } = resolveReferences(statements);
    expect(errors).toHaveLength(0);
    expect(resolved.get("x")).toEqual({ kind: "reference", name: "unknown" });
  });

  it("uses last statement as root by default", () => {
    const statements: Statement[] = [
      { name: "a", value: { kind: "literal", value: 1 } },
      { name: "b", value: { kind: "literal", value: 2 } },
    ];

    const { root } = resolveReferences(statements);
    expect(root).toEqual({ kind: "literal", value: 2 });
  });

  it("uses statement named 'root' as root", () => {
    const statements: Statement[] = [
      { name: "root", value: { kind: "literal", value: "I am root" } },
      { name: "other", value: { kind: "literal", value: "not root" } },
    ];

    const { root } = resolveReferences(statements);
    expect(root).toEqual({ kind: "literal", value: "I am root" });
  });

  it("resolves references in arrays", () => {
    const statements: Statement[] = [
      { name: "item", value: { kind: "literal", value: "hello" } },
      {
        name: "list",
        value: {
          kind: "array",
          elements: [{ kind: "reference", name: "item" }],
        },
      },
    ];

    const { resolved } = resolveReferences(statements);
    const list = resolved.get("list");
    if (list?.kind === "array") {
      expect(list.elements[0]).toEqual({ kind: "literal", value: "hello" });
    }
  });
});
