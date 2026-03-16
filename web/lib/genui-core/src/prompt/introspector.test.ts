import { describe, it, expect } from "vitest";
import { z } from "zod";
import { zodToTypeString, schemaToSignature } from "./introspector";

describe("zodToTypeString", () => {
  it("handles primitives", () => {
    expect(zodToTypeString(z.string())).toBe("string");
    expect(zodToTypeString(z.number())).toBe("number");
    expect(zodToTypeString(z.boolean())).toBe("boolean");
    expect(zodToTypeString(z.null())).toBe("null");
  });

  it("handles optional", () => {
    expect(zodToTypeString(z.string().optional())).toBe("string?");
  });

  it("handles nullable", () => {
    expect(zodToTypeString(z.string().nullable())).toBe("string | null");
  });

  it("handles enums", () => {
    expect(zodToTypeString(z.enum(["a", "b", "c"]))).toBe('"a" | "b" | "c"');
  });

  it("handles arrays", () => {
    expect(zodToTypeString(z.array(z.string()))).toBe("string[]");
  });

  it("handles objects", () => {
    const schema = z.object({
      name: z.string(),
      age: z.number().optional(),
    });
    expect(zodToTypeString(schema)).toBe("{ name: string, age?: number }");
  });

  it("handles defaults", () => {
    expect(zodToTypeString(z.string().default("hello"))).toBe("string?");
  });
});

describe("schemaToSignature", () => {
  it("generates a function-like signature", () => {
    const schema = z.object({
      label: z.string(),
      main: z.boolean().optional(),
      primary: z.boolean().optional(),
    });

    expect(schemaToSignature("Button", schema)).toBe(
      "Button(label: string, main?: boolean, primary?: boolean)"
    );
  });

  it("handles required-only params", () => {
    const schema = z.object({
      title: z.string(),
      color: z.string(),
    });

    expect(schemaToSignature("Tag", schema)).toBe(
      "Tag(title: string, color: string)"
    );
  });

  it("handles enum params", () => {
    const schema = z.object({
      size: z.enum(["sm", "md", "lg"]).optional(),
    });

    expect(schemaToSignature("Widget", schema)).toBe(
      'Widget(size?: "sm" | "md" | "lg")'
    );
  });
});
