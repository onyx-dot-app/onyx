import {
  flatFields,
  isEcho,
  isEmptyPayload,
} from "@/lib/timeline/chat/toolPayload";
import type { JsonValue } from "@/lib/json";

describe("flatFields", () => {
  test("lists a flat object", () => {
    expect(flatFields({ repo: "onyx", limit: 3, draft: false })).toEqual([
      ["repo", "onyx"],
      ["limit", "3"],
      ["draft", "false"],
    ]);
  });

  test.each<[string, JsonValue | undefined]>([
    ["nested", { options: { max: 2 } }],
    ["array value", { fields: ["a"] }],
    ["array", [1, 2]],
    ["multiline", { text: "a\nb" }],
    ["long", { text: "x".repeat(121) }],
    ["empty", {}],
    ["text", "hello"],
    ["null", null],
  ])("returns null for %s", (_, payload) => {
    expect(flatFields(payload)).toBeNull();
  });
});

describe("isEmptyPayload", () => {
  test.each<[JsonValue | undefined, boolean]>([
    [null, true],
    [undefined, true],
    ["  ", true],
    [{}, true],
    [[], true],
    ["ok", false],
    [0, false],
    [{ a: 1 }, false],
  ])("%j -> %s", (payload, empty) => {
    expect(isEmptyPayload(payload)).toBe(empty);
  });
});

describe("isEcho", () => {
  test("a response with the request's own fields repeats it", () => {
    expect(isEcho([["name", "pptx"]], [["name", "pptx"]])).toBe(true);
  });

  test("the same value under another key is a real answer", () => {
    expect(isEcho([["count", "3"]], [["limit", "3"]])).toBe(false);
    expect(isEcho([["status", "open"]], [["state", "open"]])).toBe(false);
  });

  test("a payload that is not flat fields is never an echo", () => {
    expect(isEcho(null, [["name", "pptx"]])).toBe(false);
  });
});
