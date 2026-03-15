import { describe, it, expect } from "vitest";
import { autoClose } from "./autoclose";

describe("autoClose", () => {
  it("closes unmatched parentheses", () => {
    expect(autoClose('Button("hello"')).toBe('Button("hello")');
  });

  it("closes unmatched brackets", () => {
    expect(autoClose('["a", "b"')).toBe('["a", "b"]');
  });

  it("closes unmatched braces", () => {
    expect(autoClose('{name: "test"')).toBe('{name: "test"}');
  });

  it("closes unmatched strings", () => {
    expect(autoClose('"hello')).toBe('"hello"');
  });

  it("closes nested brackets", () => {
    expect(autoClose("Foo([1, 2")).toBe("Foo([1, 2])");
  });

  it("handles already closed input", () => {
    expect(autoClose('Button("ok")')).toBe('Button("ok")');
  });

  it("handles empty input", () => {
    expect(autoClose("")).toBe("");
  });

  it("handles escaped quotes inside strings", () => {
    expect(autoClose('"hello \\"world')).toBe('"hello \\"world"');
  });

  it("handles deeply nested structures", () => {
    expect(autoClose('Stack([Row([Text("hi"')).toBe(
      'Stack([Row([Text("hi")])])',
    );
  });
});
