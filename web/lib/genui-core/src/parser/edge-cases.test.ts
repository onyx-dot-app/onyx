import { describe, it, expect } from "vitest";
import { Tokenizer } from "./tokenizer";
import { Parser } from "./parser";
import { TokenType } from "../types";

// ── Helpers ──

function tokenize(input: string) {
  return new Tokenizer(input).tokenize();
}

function tokenTypes(input: string): TokenType[] {
  return tokenize(input).map((t) => t.type);
}

function tokenValues(input: string): string[] {
  return tokenize(input).map((t) => t.value);
}

function parseStatements(input: string) {
  return Parser.fromSource(input).parse();
}

// ────────────────────────────────────────────────────────────
//  Tokenizer edge cases
// ────────────────────────────────────────────────────────────

describe("Tokenizer edge cases", () => {
  it("handles empty string", () => {
    const tokens = tokenize("");
    expect(tokens).toHaveLength(1);
    expect(tokens[0]!.type).toBe(TokenType.EOF);
  });

  it("handles only whitespace (spaces and tabs)", () => {
    const tokens = tokenize("   \t\t   ");
    expect(tokens).toHaveLength(1);
    expect(tokens[0]!.type).toBe(TokenType.EOF);
  });

  it("handles only newlines", () => {
    const types = tokenTypes("\n\n\n");
    // Each newline at bracket depth 0 produces a Newline token
    expect(types.filter((t) => t === TokenType.Newline).length).toBe(3);
    expect(types[types.length - 1]).toBe(TokenType.EOF);
  });

  it("handles unicode in string literals (emoji)", () => {
    const tokens = tokenize('"hello \u{1F680}\u{1F525}"');
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str).toBeDefined();
    expect(str!.value).toBe("hello \u{1F680}\u{1F525}");
  });

  it("handles unicode in string literals (CJK characters)", () => {
    const tokens = tokenize('"\u4F60\u597D\u4E16\u754C"');
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str!.value).toBe("\u4F60\u597D\u4E16\u754C");
  });

  it("handles very long string literals (1000+ chars)", () => {
    const longContent = "a".repeat(2000);
    const tokens = tokenize(`"${longContent}"`);
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str!.value).toBe(longContent);
    expect(str!.value.length).toBe(2000);
  });

  it("handles deeply nested brackets (10+ levels)", () => {
    const open = "(".repeat(15);
    const close = ")".repeat(15);
    const input = `Foo${open}${close}`;
    const tokens = tokenize(input);
    const lParens = tokens.filter((t) => t.type === TokenType.LParen);
    const rParens = tokens.filter((t) => t.type === TokenType.RParen);
    expect(lParens).toHaveLength(15);
    expect(rParens).toHaveLength(15);
  });

  it("suppresses newlines inside brackets", () => {
    const input = '(\n\n"hello"\n\n)';
    const types = tokenTypes(input);
    // Newlines inside brackets should be suppressed
    expect(types).not.toContain(TokenType.Newline);
    expect(types).toContain(TokenType.LParen);
    expect(types).toContain(TokenType.String);
    expect(types).toContain(TokenType.RParen);
  });

  it("handles single-quoted strings", () => {
    const tokens = tokenize("'hello world'");
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str!.value).toBe("hello world");
  });

  it("handles double-quoted strings", () => {
    const tokens = tokenize('"hello world"');
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str!.value).toBe("hello world");
  });

  it("handles single quotes inside double-quoted strings without escaping", () => {
    const tokens = tokenize('"it\'s fine"');
    // The \' escape yields a literal '
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str!.value).toBe("it's fine");
  });

  it("handles negative decimals (-3.14)", () => {
    const tokens = tokenize("-3.14");
    const num = tokens.find((t) => t.type === TokenType.Number);
    expect(num).toBeDefined();
    expect(num!.value).toBe("-3.14");
  });

  it("handles negative integers", () => {
    const tokens = tokenize("-42");
    const num = tokens.find((t) => t.type === TokenType.Number);
    expect(num!.value).toBe("-42");
  });

  it("handles multiple consecutive comments", () => {
    const input = "// comment 1\n// comment 2\n// comment 3\nx";
    const tokens = tokenize(input);
    // Comments are skipped; we should get newlines and the identifier
    const identifiers = tokens.filter((t) => t.type === TokenType.Identifier);
    expect(identifiers).toHaveLength(1);
    expect(identifiers[0]!.value).toBe("x");
  });

  it("handles comment at end of file (no trailing newline)", () => {
    const input = "x = 1\n// trailing comment";
    const tokens = tokenize(input);
    // Should not crash, last token is EOF
    expect(tokens[tokens.length - 1]!.type).toBe(TokenType.EOF);
    // The identifier and number should be present
    expect(
      tokens.some((t) => t.type === TokenType.Identifier && t.value === "x")
    ).toBe(true);
    expect(
      tokens.some((t) => t.type === TokenType.Number && t.value === "1")
    ).toBe(true);
  });

  it("handles all escape sequences in strings", () => {
    const input = '"\\n\\t\\\\\\"\\\'"';
    const tokens = tokenize(input);
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str!.value).toBe("\n\t\\\"'");
  });

  it("handles unknown escape sequences by preserving the escaped char", () => {
    const tokens = tokenize('"\\x"');
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str!.value).toBe("x");
  });

  it("handles unterminated string (EOF inside string)", () => {
    // Should not throw; tokenizer consumes until EOF
    const tokens = tokenize('"unterminated');
    const str = tokens.find((t) => t.type === TokenType.String);
    expect(str).toBeDefined();
    expect(str!.value).toBe("unterminated");
  });

  it("handles bracket depth never going below zero on unmatched closing brackets", () => {
    // Extra closing parens should not crash
    const tokens = tokenize(")))]]]");
    expect(tokens[tokens.length - 1]!.type).toBe(TokenType.EOF);
  });

  it("skips unknown characters silently", () => {
    const tokens = tokenize("@ # $ %");
    // All unknown chars are skipped, only EOF remains
    expect(tokens).toHaveLength(1);
    expect(tokens[0]!.type).toBe(TokenType.EOF);
  });

  it("tracks line and column correctly across newlines", () => {
    const tokens = tokenize("x\ny");
    const x = tokens.find((t) => t.value === "x");
    const y = tokens.find((t) => t.value === "y");
    expect(x!.line).toBe(1);
    expect(x!.column).toBe(1);
    expect(y!.line).toBe(2);
    expect(y!.column).toBe(1);
  });

  it("treats identifier starting with underscore as valid", () => {
    const tokens = tokenize("_foo _bar123");
    const idents = tokens.filter((t) => t.type === TokenType.Identifier);
    expect(idents).toHaveLength(2);
    expect(idents[0]!.value).toBe("_foo");
    expect(idents[1]!.value).toBe("_bar123");
  });

  it("tokenizes number with trailing dot as number then unknown", () => {
    // "42." => number "42." (reads the dot as part of decimal), then EOF
    const tokens = tokenize("42.");
    const num = tokens.find((t) => t.type === TokenType.Number);
    expect(num!.value).toBe("42.");
  });
});

// ────────────────────────────────────────────────────────────
//  Parser edge cases
// ────────────────────────────────────────────────────────────

describe("Parser edge cases", () => {
  it("handles empty input", () => {
    const { statements, errors } = parseStatements("");
    expect(statements).toHaveLength(0);
    expect(errors).toHaveLength(0);
  });

  it("handles single identifier with no assignment (error recovery)", () => {
    const { statements, errors } = parseStatements("foo");
    // Should produce an error because it expects `=` after identifier
    expect(errors.length).toBeGreaterThan(0);
    expect(errors[0]!.message).toContain("Expected Equals");
  });

  it("handles assignment with no value (error recovery)", () => {
    const { statements, errors } = parseStatements("x =");
    // Should produce an error because there's no expression after `=`
    expect(errors.length).toBeGreaterThan(0);
  });

  it("parses component with 0 args: Foo()", () => {
    const { statements, errors } = parseStatements("x = Foo()");
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(1);
    const node = statements[0]!.value;
    expect(node.kind).toBe("component");
    if (node.kind === "component") {
      expect(node.name).toBe("Foo");
      expect(node.args).toHaveLength(0);
    }
  });

  it("parses component with only named args", () => {
    const { statements, errors } = parseStatements("x = Foo(a: 1, b: 2)");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "component") {
      expect(node.args).toHaveLength(2);
      expect(node.args[0]!.key).toBe("a");
      expect(node.args[0]!.value).toEqual({ kind: "literal", value: 1 });
      expect(node.args[1]!.key).toBe("b");
      expect(node.args[1]!.value).toEqual({ kind: "literal", value: 2 });
    }
  });

  it("parses deeply nested components", () => {
    const { statements, errors } = parseStatements('x = A(B(C(D("deep"))))');
    expect(errors).toHaveLength(0);
    const a = statements[0]!.value;
    expect(a.kind).toBe("component");
    if (a.kind === "component") {
      expect(a.name).toBe("A");
      const b = a.args[0]!.value;
      expect(b.kind).toBe("component");
      if (b.kind === "component") {
        expect(b.name).toBe("B");
        const c = b.args[0]!.value;
        expect(c.kind).toBe("component");
        if (c.kind === "component") {
          expect(c.name).toBe("C");
          const d = c.args[0]!.value;
          expect(d.kind).toBe("component");
          if (d.kind === "component") {
            expect(d.name).toBe("D");
            expect(d.args[0]!.value).toEqual({
              kind: "literal",
              value: "deep",
            });
          }
        }
      }
    }
  });

  it("parses array of arrays", () => {
    const { statements, errors } = parseStatements("x = [[1, 2], [3, 4]]");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("array");
    if (node.kind === "array") {
      expect(node.elements).toHaveLength(2);
      const first = node.elements[0]!;
      expect(first.kind).toBe("array");
      if (first.kind === "array") {
        expect(first.elements).toEqual([
          { kind: "literal", value: 1 },
          { kind: "literal", value: 2 },
        ]);
      }
      const second = node.elements[1]!;
      if (second.kind === "array") {
        expect(second.elements).toEqual([
          { kind: "literal", value: 3 },
          { kind: "literal", value: 4 },
        ]);
      }
    }
  });

  it("parses object with string keys (including spaces)", () => {
    const { statements, errors } = parseStatements(
      'x = {"key with spaces": 1, "another key": 2}'
    );
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("object");
    if (node.kind === "object") {
      expect(node.entries).toHaveLength(2);
      expect(node.entries[0]!.key).toBe("key with spaces");
      expect(node.entries[0]!.value).toEqual({ kind: "literal", value: 1 });
      expect(node.entries[1]!.key).toBe("another key");
    }
  });

  it("handles trailing newlines gracefully", () => {
    const { statements, errors } = parseStatements('x = "hello"\n\n\n');
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(1);
  });

  it("handles leading newlines gracefully", () => {
    const { statements, errors } = parseStatements('\n\n\nx = "hello"');
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(1);
    expect(statements[0]!.name).toBe("x");
  });

  it("handles multiple empty lines between statements", () => {
    const { statements, errors } = parseStatements("x = 1\n\n\n\n\ny = 2");
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(2);
    expect(statements[0]!.name).toBe("x");
    expect(statements[1]!.name).toBe("y");
  });

  it("treats PascalCase identifiers as components, not keywords: True", () => {
    // `True` is PascalCase, so it should be parsed as a component call (not boolean)
    // when followed by parens
    const { statements, errors } = parseStatements("x = True()");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("component");
    if (node.kind === "component") {
      expect(node.name).toBe("True");
    }
  });

  it("treats PascalCase identifiers as components: Null", () => {
    const { statements, errors } = parseStatements("x = Null()");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("component");
    if (node.kind === "component") {
      expect(node.name).toBe("Null");
    }
  });

  it("treats lowercase 'true' as boolean literal, not reference", () => {
    const { statements } = parseStatements("x = true");
    expect(statements[0]!.value).toEqual({ kind: "literal", value: true });
  });

  it("treats lowercase 'null' as null literal, not reference", () => {
    const { statements } = parseStatements("x = null");
    expect(statements[0]!.value).toEqual({ kind: "literal", value: null });
  });

  it("handles very long identifier names", () => {
    const longName = "a".repeat(500);
    const { statements, errors } = parseStatements(`${longName} = 42`);
    expect(errors).toHaveLength(0);
    expect(statements[0]!.name).toBe(longName);
  });

  it("parses mixed named and positional args", () => {
    const { statements, errors } = parseStatements(
      'x = Foo("pos", named: "val", "pos2")'
    );
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "component") {
      expect(node.args).toHaveLength(3);
      // First: positional
      expect(node.args[0]!.key).toBeNull();
      expect(node.args[0]!.value).toEqual({ kind: "literal", value: "pos" });
      // Second: named
      expect(node.args[1]!.key).toBe("named");
      expect(node.args[1]!.value).toEqual({ kind: "literal", value: "val" });
      // Third: positional
      expect(node.args[2]!.key).toBeNull();
      expect(node.args[2]!.value).toEqual({ kind: "literal", value: "pos2" });
    }
  });

  it("handles trailing comma in component args", () => {
    const { statements, errors } = parseStatements("x = Foo(1, 2,)");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "component") {
      expect(node.args).toHaveLength(2);
    }
  });

  it("handles trailing comma in arrays", () => {
    const { statements, errors } = parseStatements("x = [1, 2, 3,]");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "array") {
      expect(node.elements).toHaveLength(3);
    }
  });

  it("handles trailing comma in objects", () => {
    const { statements, errors } = parseStatements("x = {a: 1, b: 2,}");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "object") {
      expect(node.entries).toHaveLength(2);
    }
  });

  it("recovers from error and parses subsequent statements", () => {
    const { statements, errors } = parseStatements("bad\ny = 42");
    // First statement is invalid (no `=`), second is valid
    expect(errors.length).toBeGreaterThan(0);
    expect(statements).toHaveLength(1);
    expect(statements[0]!.name).toBe("y");
    expect(statements[0]!.value).toEqual({ kind: "literal", value: 42 });
  });

  it("parses camelCase identifier as reference", () => {
    const { statements, errors } = parseStatements("x = myRef");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("reference");
    if (node.kind === "reference") {
      expect(node.name).toBe("myRef");
    }
  });

  it("parses PascalCase identifier without parens as reference", () => {
    // PascalCase but no `(` following => treated as a reference, not component
    const { statements, errors } = parseStatements("x = MyComponent");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("reference");
    if (node.kind === "reference") {
      expect(node.name).toBe("MyComponent");
    }
  });

  it("parses empty array", () => {
    const { statements, errors } = parseStatements("x = []");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("array");
    if (node.kind === "array") {
      expect(node.elements).toHaveLength(0);
    }
  });

  it("parses empty object", () => {
    const { statements, errors } = parseStatements("x = {}");
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    expect(node.kind).toBe("object");
    if (node.kind === "object") {
      expect(node.entries).toHaveLength(0);
    }
  });

  it("parses component as named arg value", () => {
    const { statements, errors } = parseStatements(
      'x = Layout(header: Header("Title"))'
    );
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "component") {
      expect(node.name).toBe("Layout");
      expect(node.args[0]!.key).toBe("header");
      const headerVal = node.args[0]!.value;
      expect(headerVal.kind).toBe("component");
      if (headerVal.kind === "component") {
        expect(headerVal.name).toBe("Header");
      }
    }
  });

  it("parses negative number in expression position", () => {
    const { statements, errors } = parseStatements("x = -3.14");
    expect(errors).toHaveLength(0);
    expect(statements[0]!.value).toEqual({ kind: "literal", value: -3.14 });
  });

  it("parses component with array arg", () => {
    const { statements, errors } = parseStatements(
      "x = List(items: [1, 2, 3])"
    );
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "component") {
      expect(node.args[0]!.key).toBe("items");
      expect(node.args[0]!.value.kind).toBe("array");
    }
  });

  it("handles comments between statements", () => {
    const input = "x = 1\n// comment\ny = 2";
    const { statements, errors } = parseStatements(input);
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(2);
  });

  it("handles comment on the same line as a statement", () => {
    // The comment eats everything after //, so `x = 1` is before the comment on a new line
    const input = "// header comment\nx = 1";
    const { statements, errors } = parseStatements(input);
    expect(errors).toHaveLength(0);
    expect(statements).toHaveLength(1);
    expect(statements[0]!.name).toBe("x");
  });

  it("parses object with mixed identifier and string keys", () => {
    const { statements, errors } = parseStatements(
      'x = {name: "Alice", "full name": "Alice B"}'
    );
    expect(errors).toHaveLength(0);
    const node = statements[0]!.value;
    if (node.kind === "object") {
      expect(node.entries[0]!.key).toBe("name");
      expect(node.entries[1]!.key).toBe("full name");
    }
  });
});
