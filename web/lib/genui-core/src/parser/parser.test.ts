import { describe, it, expect } from "vitest";
import { Parser } from "./parser";

describe("Parser", () => {
  function parseStatements(input: string) {
    const parser = Parser.fromSource(input);
    return parser.parse();
  }

  it("parses a simple literal assignment", () => {
    const { statements, errors } = parseStatements('x = "hello"');
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(1);
    expect(statements[0]!.name).toBe("x");
    expect(statements[0]!.value).toEqual({ kind: "literal", value: "hello" });
  });

  it("parses number literals", () => {
    const { statements } = parseStatements("n = 42");
    expect(statements[0]!.value).toEqual({ kind: "literal", value: 42 });
  });

  it("parses boolean literals", () => {
    const { statements } = parseStatements("b = true");
    expect(statements[0]!.value).toEqual({ kind: "literal", value: true });
  });

  it("parses null", () => {
    const { statements } = parseStatements("x = null");
    expect(statements[0]!.value).toEqual({ kind: "literal", value: null });
  });

  it("parses a component call with positional args", () => {
    const { statements, errors } = parseStatements('btn = Button("Click me")');
    expect(errors).toHaveLength(0);
    expect(statements[0]!.value).toEqual({
      kind: "component",
      name: "Button",
      args: [{ key: null, value: { kind: "literal", value: "Click me" } }],
    });
  });

  it("parses a component call with named args", () => {
    const { statements } = parseStatements('t = Tag("PDF", color: "blue")');
    const comp = statements[0]!.value;
    expect(comp.kind).toBe("component");
    if (comp.kind === "component") {
      expect(comp.args).toHaveLength(2);
      expect(comp.args[0]!.key).toBeNull();
      expect(comp.args[1]!.key).toBe("color");
    }
  });

  it("parses nested components", () => {
    const { statements, errors } = parseStatements(
      'row = Row([Button("A"), Button("B")])'
    );
    expect(errors).toHaveLength(0);
    const comp = statements[0]!.value;
    expect(comp.kind).toBe("component");
  });

  it("parses arrays", () => {
    const { statements } = parseStatements('items = ["a", "b", "c"]');
    expect(statements[0]!.value).toEqual({
      kind: "array",
      elements: [
        { kind: "literal", value: "a" },
        { kind: "literal", value: "b" },
        { kind: "literal", value: "c" },
      ],
    });
  });

  it("parses objects", () => {
    const { statements } = parseStatements('opts = {name: "test", count: 5}');
    expect(statements[0]!.value).toEqual({
      kind: "object",
      entries: [
        { key: "name", value: { kind: "literal", value: "test" } },
        { key: "count", value: { kind: "literal", value: 5 } },
      ],
    });
  });

  it("parses variable references", () => {
    const { statements } = parseStatements("ref = myVar");
    expect(statements[0]!.value).toEqual({ kind: "reference", name: "myVar" });
  });

  it("parses multiple statements", () => {
    const { statements, errors } = parseStatements(
      'title = Text("Hello")\nbtn = Button("Click")'
    );
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(2);
    expect(statements[0]!.name).toBe("title");
    expect(statements[1]!.name).toBe("btn");
  });

  it("handles trailing commas", () => {
    const { statements, errors } = parseStatements('x = Button("a", "b",)');
    expect(errors).toHaveLength(0);
    const comp = statements[0]!.value;
    if (comp.kind === "component") {
      expect(comp.args).toHaveLength(2);
    }
  });

  it("recovers from parse errors", () => {
    const { statements, errors } = parseStatements(
      '!!invalid!!\ny = Text("valid")'
    );
    expect(errors.length).toBeGreaterThan(0);
    // Should still parse the valid second line
    expect(statements.length).toBeGreaterThanOrEqual(1);
  });

  it("parses the full example from the spec", () => {
    const input = `title = Text("Search Results", headingH2: true)
row1 = ["Onyx Docs", Tag("PDF", color: "blue"), "2024-01-15"]
row2 = ["API Guide", Tag("MD", color: "green"), "2024-02-01"]
results = Table(["Name", "Type", "Date"], [row1, row2])
action = Button("View All", main: true, primary: true, actionId: "viewAll")
root = Stack([title, results, action], gap: "md")`;

    const { statements, errors } = parseStatements(input);
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(6);
    expect(statements[5]!.name).toBe("root");
  });
});
