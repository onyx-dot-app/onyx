import { describe, it, expect } from "vitest";
import { Tokenizer } from "./tokenizer";
import { TokenType } from "../types";

describe("Tokenizer", () => {
  function tokenTypes(input: string): TokenType[] {
    return new Tokenizer(input).tokenize().map((t) => t.type);
  }

  function tokenValues(input: string): string[] {
    return new Tokenizer(input).tokenize().map((t) => t.value);
  }

  it("tokenizes a simple assignment", () => {
    const tokens = new Tokenizer('x = "hello"').tokenize();
    expect(tokens.map((t) => t.type)).toEqual([
      TokenType.Identifier,
      TokenType.Equals,
      TokenType.String,
      TokenType.EOF,
    ]);
    expect(tokens[0]!.value).toBe("x");
    expect(tokens[2]!.value).toBe("hello");
  });

  it("tokenizes a component call", () => {
    expect(tokenTypes('Button("Click me", main: true)')).toEqual([
      TokenType.Identifier,
      TokenType.LParen,
      TokenType.String,
      TokenType.Comma,
      TokenType.Identifier,
      TokenType.Colon,
      TokenType.Boolean,
      TokenType.RParen,
      TokenType.EOF,
    ]);
  });

  it("tokenizes arrays", () => {
    expect(tokenTypes('["a", "b", "c"]')).toEqual([
      TokenType.LBracket,
      TokenType.String,
      TokenType.Comma,
      TokenType.String,
      TokenType.Comma,
      TokenType.String,
      TokenType.RBracket,
      TokenType.EOF,
    ]);
  });

  it("tokenizes objects", () => {
    expect(tokenTypes('{name: "Alice", age: 30}')).toEqual([
      TokenType.LBrace,
      TokenType.Identifier,
      TokenType.Colon,
      TokenType.String,
      TokenType.Comma,
      TokenType.Identifier,
      TokenType.Colon,
      TokenType.Number,
      TokenType.RBrace,
      TokenType.EOF,
    ]);
  });

  it("tokenizes numbers including negatives and decimals", () => {
    const tokens = new Tokenizer("42 -7 3.14").tokenize();
    const numbers = tokens.filter((t) => t.type === TokenType.Number);
    expect(numbers.map((t) => t.value)).toEqual(["42", "-7", "3.14"]);
  });

  it("tokenizes booleans and null", () => {
    expect(tokenTypes("true false null")).toEqual([
      TokenType.Boolean,
      TokenType.Boolean,
      TokenType.Null,
      TokenType.EOF,
    ]);
  });

  it("handles escaped strings", () => {
    const tokens = new Tokenizer('"hello \\"world\\""').tokenize();
    expect(tokens[0]!.value).toBe('hello "world"');
  });

  it("emits newlines only at bracket depth 0", () => {
    // Inside parens — newlines suppressed
    const inside = tokenTypes('Foo(\n"a",\n"b"\n)');
    expect(inside.filter((t) => t === TokenType.Newline)).toHaveLength(0);

    // At top level — newlines emitted
    const outside = tokenTypes("x = 1\ny = 2");
    expect(outside.filter((t) => t === TokenType.Newline)).toHaveLength(1);
  });

  it("skips line comments", () => {
    const tokens = new Tokenizer(
      "x = 1 // this is a comment\ny = 2",
    ).tokenize();
    const idents = tokens.filter((t) => t.type === TokenType.Identifier);
    expect(idents.map((t) => t.value)).toEqual(["x", "y"]);
  });

  it("tracks line and column numbers", () => {
    const tokens = new Tokenizer("x = 1\ny = 2").tokenize();
    const y = tokens.find((t) => t.value === "y");
    expect(y?.line).toBe(2);
  });
});
