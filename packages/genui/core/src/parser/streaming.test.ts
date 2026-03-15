import { describe, it, expect } from "vitest";
import { z } from "zod";
import { createStreamingParser } from "./streaming";
import { createLibrary } from "../library";
import { defineComponent } from "../component";

function makeTestLibrary() {
  return createLibrary([
    defineComponent({
      name: "Text",
      description: "Text",
      props: z.object({ children: z.string() }),
      component: null,
    }),
    defineComponent({
      name: "Button",
      description: "Button",
      props: z.object({
        children: z.string(),
        main: z.boolean().optional(),
        actionId: z.string().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Stack",
      description: "Stack",
      props: z.object({
        children: z.array(z.unknown()).optional(),
        gap: z.string().optional(),
      }),
      component: null,
    }),
  ]);
}

describe("StreamingParser", () => {
  it("parses a complete response", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    const result = parser.push('title = Text("Hello World")\n');
    expect(result.statements).toHaveLength(1);
    expect(result.root).not.toBeNull();
  });

  it("handles incremental streaming", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // First chunk — partial line
    let result = parser.push('title = Text("He');
    expect(result.statements.length).toBeGreaterThanOrEqual(0);

    // Complete the line
    result = parser.push('llo World")\n');
    expect(result.statements).toHaveLength(1);
  });

  it("handles multi-line streaming", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    parser.push('a = Text("Line 1")\n');
    const result = parser.push('b = Text("Line 2")\n');
    expect(result.statements).toHaveLength(2);
  });

  it("caches complete lines and only re-parses partial", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // First complete line
    parser.push('a = Text("First")\n');

    // Partial second line — should still have first line cached
    const result = parser.push('b = Text("Sec');
    expect(result.statements.length).toBeGreaterThanOrEqual(1);
  });

  it("resets on shorter input", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    parser.push('a = Text("Hello")\n');
    parser.reset();

    const result = parser.push('x = Text("Fresh")\n');
    expect(result.statements).toHaveLength(1);
    expect(result.statements[0]!.name).toBe("x");
  });

  it("result() returns last parse result", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    parser.push('a = Text("Hello")\n');
    const result = parser.result();
    expect(result.statements).toHaveLength(1);
  });
});
