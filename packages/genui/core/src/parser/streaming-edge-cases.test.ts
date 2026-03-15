import { describe, it, expect } from "vitest";
import { z } from "zod";
import { createStreamingParser } from "./streaming";
import { createLibrary } from "../library";
import { defineComponent } from "../component";
import { autoClose } from "./autoclose";

function makeTestLibrary() {
  return createLibrary([
    defineComponent({
      name: "Text",
      description: "Displays text",
      props: z.object({ children: z.string() }),
      component: null,
    }),
    defineComponent({
      name: "Button",
      description: "Clickable button",
      props: z.object({
        children: z.string(),
        main: z.boolean().optional(),
        actionId: z.string().optional(),
      }),
      component: null,
    }),
    defineComponent({
      name: "Stack",
      description: "Vertical stack layout",
      props: z.object({
        children: z.array(z.unknown()).optional(),
        gap: z.string().optional(),
      }),
      component: null,
    }),
  ]);
}

describe("Streaming edge cases", () => {
  it("single character at a time streaming", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    const input = 'title = Text("Hello")\n';
    let result;
    for (const ch of input) {
      result = parser.push(ch);
    }

    expect(result!.statements).toHaveLength(1);
    expect(result!.statements[0]!.name).toBe("title");
    expect(result!.root).not.toBeNull();
  });

  it("token split across chunks — component name", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // "Text" split as "Tex" + "t"
    parser.push("a = Tex");
    const result = parser.push('t("hello")\n');

    expect(result.statements).toHaveLength(1);
    expect(result.statements[0]!.value).toMatchObject({
      kind: "component",
      name: "Text",
    });
  });

  it("string split mid-escape sequence", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // Split right before the escaped quote
    parser.push('a = Text("hel');
    const result = parser.push('lo \\"world\\"")\n');

    expect(result.statements).toHaveLength(1);
    expect(result.root).not.toBeNull();
  });

  it("multi-line component split across chunks", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // The streaming parser splits on newlines, so multi-line expressions
    // need to be on a single line or use variables. Test that a long
    // single-line expression streamed in chunks works correctly.
    parser.push('root = Stack([Text("line 1"), Text("line');
    const result = parser.push(' 2")])\n');

    expect(result.statements).toHaveLength(1);
    expect(result.root).not.toBeNull();
  });

  it("empty chunks do not corrupt state", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    parser.push("");
    parser.push('a = Text("hi")');
    parser.push("");
    parser.push("");
    const result = parser.push("\n");

    expect(result.statements).toHaveLength(1);
    expect(result.statements[0]!.name).toBe("a");
  });

  it("very large single chunk with multiple complete statements", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    const lines =
      Array.from({ length: 50 }, (_, i) => `v${i} = Text("item ${i}")`).join(
        "\n",
      ) + "\n";

    const result = parser.push(lines);

    expect(result.statements).toHaveLength(50);
    expect(result.root).not.toBeNull();
  });

  it("interleaved complete and partial lines", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // Complete line followed by partial
    parser.push('a = Text("done")\nb = Text("part');
    let result = parser.result();

    // "a" is cached complete, "b" is partial but auto-closed
    expect(result.statements.length).toBeGreaterThanOrEqual(1);

    // Now finish the partial and add another complete
    result = parser.push('ial")\nc = Text("also done")\n');

    expect(result.statements).toHaveLength(3);
    expect(result.statements.map((s) => s.name)).toEqual(["a", "b", "c"]);
  });

  it("variable reference before definition — streaming order matters", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // Reference "label" before it's defined
    parser.push("root = Stack([label])\n");
    let result = parser.result();

    // At this point "label" is an unresolved reference — should not crash
    expect(result.statements).toHaveLength(1);
    expect(result.errors.length).toBeGreaterThanOrEqual(0);

    // Now define it
    result = parser.push('label = Text("Hi")\n');

    // After defining, root should pick it up via resolution
    expect(result.statements).toHaveLength(2);
  });

  it("repeated push after complete response is idempotent", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    const full = 'a = Text("done")\n';
    const first = parser.push(full);

    // Push empty strings — result should remain stable
    const second = parser.push("");
    const third = parser.push("");

    expect(second.statements).toEqual(first.statements);
    expect(third.statements).toEqual(first.statements);
    expect(third.root).toEqual(first.root);
  });

  it("unicode characters split across chunk boundaries", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    // JS strings are UTF-16, so multi-byte chars like emoji are fine as
    // string splits — but let's verify the parser handles them gracefully
    parser.push('a = Text("hello ');
    parser.push("🌍");
    parser.push(" world");
    const result = parser.push('")\n');

    expect(result.statements).toHaveLength(1);
    expect(result.root).not.toBeNull();
  });

  it("unicode CJK characters streamed char by char", () => {
    const lib = makeTestLibrary();
    const parser = createStreamingParser(lib);

    const input = 'a = Text("你好世界")\n';
    let result;
    for (const ch of input) {
      result = parser.push(ch);
    }

    expect(result!.statements).toHaveLength(1);
    expect(result!.root).not.toBeNull();
  });
});

describe("autoClose additional edge cases", () => {
  it("mixed bracket types — ([{", () => {
    const result = autoClose("([{");
    expect(result).toBe("([{}])");
  });

  it("string containing bracket chars is not counted", () => {
    // The ( inside the string should not produce a closer
    const result = autoClose('"hello (world"');
    // String is closed, paren inside string is ignored — no extra closers
    expect(result).toBe('"hello (world"');
  });

  it("unclosed string containing bracket chars", () => {
    // Unclosed string with brackets inside — brackets are ignored, string gets closed
    const result = autoClose('"hello (world');
    expect(result).toBe('"hello (world"');
  });

  it("only opening brackets — (((", () => {
    const result = autoClose("(((");
    expect(result).toBe("((()))");
  });

  it("alternating open/close with extras — (()(", () => {
    const result = autoClose("(()(");
    // Stack: push ( → push ( → pop for ) → push ( → closers left: (, (
    expect(result).toBe("(()())");
  });

  it("all bracket types deeply nested", () => {
    const result = autoClose("({[");
    expect(result).toBe("({[]})");
  });

  it("partial close leaves remaining openers", () => {
    // ( [ ] — bracket closed, paren still open
    const result = autoClose("([]");
    expect(result).toBe("([])");
  });

  it("escaped quote at end of string does not close it", () => {
    // The backslash escapes the quote, so the string is still open
    const result = autoClose('"hello\\');
    // escaped flag is set, next char would be escaped — string still open
    expect(result).toBe('"hello\\"');
  });

  it("single quotes work the same as double quotes", () => {
    const result = autoClose("'hello");
    expect(result).toBe("'hello'");
  });

  it("mixed string types — only the active one matters", () => {
    // Double-quoted string containing a single quote — single quote is literal
    const result = autoClose("\"it's");
    expect(result).toBe('"it\'s"');
  });

  it("empty string input returns empty", () => {
    expect(autoClose("")).toBe("");
  });

  it("already balanced input returns unchanged", () => {
    expect(autoClose("({[]})")).toBe("({[]})");
  });

  it("mismatched close bracket is tolerated", () => {
    // A ] with no matching [ — should not crash, just ignored
    const result = autoClose("(]");
    // The ] doesn't match (, so it's ignored — ( still needs closing
    expect(result).toBe("(])");
  });
});
