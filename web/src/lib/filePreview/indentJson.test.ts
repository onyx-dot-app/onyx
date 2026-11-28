import { indentJson } from "@/lib/filePreview/indentJson";

describe("indentJson", () => {
  test("indents single-line JSON", () => {
    expect(indentJson('{"a":{"b":[1, 2]},"c":[],"d":{ }}\n')).toBe(
      '{\n  "a": {\n    "b": [\n      1,\n      2\n    ]\n  },\n  "c": [],\n  "d": {}\n}'
    );
  });

  test("keeps numbers as written", () => {
    expect(indentJson('{"id":9007199254740993,"ratio":1.0,"e":1E+2}')).toBe(
      '{\n  "id": 9007199254740993,\n  "ratio": 1.0,\n  "e": 1E+2\n}'
    );
  });

  test("keeps key order and duplicate keys", () => {
    expect(indentJson('{"b":1,"2":2,"a":3,"a":4}')).toBe(
      '{\n  "b": 1,\n  "2": 2,\n  "a": 3,\n  "a": 4\n}'
    );
  });

  test("leaves strings unchanged, also with escaped quotes", () => {
    expect(indentJson('{"say":"a \\"b, {c}\\": [d]\\\\","t":"x y"}')).toBe(
      '{\n  "say": "a \\"b, {c}\\": [d]\\\\",\n  "t": "x y"\n}'
    );
  });

  test("leaves JSON with line breaks unchanged", () => {
    const text = '{\n    "b": 1.0,\n    "a": [1,2]\n}\n';
    expect(indentJson(text)).toBe(text);
    expect(indentJson('{\r  "a": 1\r}')).toBe('{\r  "a": 1\r}');
  });

  test("leaves deeply nested JSON unchanged when indenting would make it huge", () => {
    const text = "[".repeat(5_000) + "0" + "]".repeat(5_000);
    expect(indentJson(text)).toBe(text);
  });

  test("leaves text that is not JSON unchanged", () => {
    expect(indentJson('{"a":1}}')).toBe('{"a":1}}');
  });
});
