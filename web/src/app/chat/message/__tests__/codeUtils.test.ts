import { markdownToHtml, parseMarkdownToSegments } from "../codeUtils";

describe("markdownToHtml", () => {
  test("converts bold text with asterisks and underscores", () => {
    expect(markdownToHtml("This is **bold** text")).toBe(
      "<p>This is <strong>bold</strong> text</p>"
    );
    expect(markdownToHtml("This is __bold__ text")).toBe(
      "<p>This is <strong>bold</strong> text</p>"
    );
  });

  test("converts italic text with asterisks and underscores", () => {
    expect(markdownToHtml("This is *italic* text")).toBe(
      "<p>This is <em>italic</em> text</p>"
    );
    expect(markdownToHtml("This is _italic_ text")).toBe(
      "<p>This is <em>italic</em> text</p>"
    );
  });

  test("handles mixed bold and italic", () => {
    expect(markdownToHtml("This is **bold** and *italic* text")).toBe(
      "<p>This is <strong>bold</strong> and <em>italic</em> text</p>"
    );
    expect(markdownToHtml("This is __bold__ and _italic_ text")).toBe(
      "<p>This is <strong>bold</strong> and <em>italic</em> text</p>"
    );
  });

  test("handles text with spaces and special characters", () => {
    expect(markdownToHtml("This is *as delicious and* tasty")).toBe(
      "<p>This is <em>as delicious and</em> tasty</p>"
    );
    expect(markdownToHtml("This is _as delicious and_ tasty")).toBe(
      "<p>This is <em>as delicious and</em> tasty</p>"
    );
  });

  test("handles multi-paragraph text with italics", () => {
    const input =
      "Sure! Here is a sentence with one italicized word:\n\nThe cake was _delicious_ and everyone enjoyed it.";
    expect(markdownToHtml(input)).toBe(
      "<p>Sure! Here is a sentence with one italicized word:</p>\n<p>The cake was <em>delicious</em> and everyone enjoyed it.</p>"
    );
  });

  test("handles malformed markdown without crashing", () => {
    expect(markdownToHtml("This is *malformed markdown")).toBe(
      "<p>This is *malformed markdown</p>"
    );
    expect(markdownToHtml("This is _also malformed")).toBe(
      "<p>This is _also malformed</p>"
    );
    expect(markdownToHtml("This has **unclosed bold")).toBe(
      "<p>This has **unclosed bold</p>"
    );
    expect(markdownToHtml("This has __unclosed bold")).toBe(
      "<p>This has __unclosed bold</p>"
    );
  });

  test("handles empty or null input", () => {
    expect(markdownToHtml("")).toBe("");
    expect(markdownToHtml(" ")).toBe("");
    expect(markdownToHtml("\n")).toBe("");
  });

  test("handles extremely long input without crashing", () => {
    const longText = "This is *italic* ".repeat(1000);
    expect(() => markdownToHtml(longText)).not.toThrow();
  });
});

describe("parseMarkdownToSegments", () => {
  test("parses italic text with asterisks", () => {
    const segments = parseMarkdownToSegments("This is *italic* text");
    expect(segments).toEqual([
      { type: "text", text: "This is ", raw: "This is ", length: 8 },
      { type: "italic", text: "italic", raw: "*italic*", length: 6 },
      { type: "text", text: " text", raw: " text", length: 5 },
    ]);
  });

  test("parses italic text with underscores", () => {
    const segments = parseMarkdownToSegments("This is _italic_ text");
    expect(segments).toEqual([
      { type: "text", text: "This is ", raw: "This is ", length: 8 },
      { type: "italic", text: "italic", raw: "_italic_", length: 6 },
      { type: "text", text: " text", raw: " text", length: 5 },
    ]);
  });

  test("parses bold text with asterisks", () => {
    const segments = parseMarkdownToSegments("This is **bold** text");
    expect(segments).toEqual([
      { type: "text", text: "This is ", raw: "This is ", length: 8 },
      { type: "bold", text: "bold", raw: "**bold**", length: 4 },
      { type: "text", text: " text", raw: " text", length: 5 },
    ]);
  });

  test("parses bold text with underscores", () => {
    const segments = parseMarkdownToSegments("This is __bold__ text");
    expect(segments).toEqual([
      { type: "text", text: "This is ", raw: "This is ", length: 8 },
      { type: "bold", text: "bold", raw: "__bold__", length: 4 },
      { type: "text", text: " text", raw: " text", length: 5 },
    ]);
  });

  test("parses text with spaces and special characters in italics", () => {
    const segments = parseMarkdownToSegments(
      "The cake was _delicious_ and everyone enjoyed it."
    );
    expect(segments).toEqual([
      { type: "text", text: "The cake was ", raw: "The cake was ", length: 13 },
      { type: "italic", text: "delicious", raw: "_delicious_", length: 9 },
      {
        type: "text",
        text: " and everyone enjoyed it.",
        raw: " and everyone enjoyed it.",
        length: 25,
      },
    ]);
  });

  test("parses multi-paragraph text with italics", () => {
    const segments = parseMarkdownToSegments(
      "Sure! Here is a sentence with one italicized word:\n\nThe cake was _delicious_ and everyone enjoyed it."
    );
    expect(segments).toEqual([
      {
        type: "text",
        text: "Sure! Here is a sentence with one italicized word:\n\nThe cake was ",
        raw: "Sure! Here is a sentence with one italicized word:\n\nThe cake was ",
        length: 65,
      },
      { type: "italic", text: "delicious", raw: "_delicious_", length: 9 },
      {
        type: "text",
        text: " and everyone enjoyed it.",
        raw: " and everyone enjoyed it.",
        length: 25,
      },
    ]);
  });

  test("handles malformed markdown without crashing", () => {
    expect(() => parseMarkdownToSegments("This is *malformed")).not.toThrow();
    expect(() =>
      parseMarkdownToSegments("This is _also malformed")
    ).not.toThrow();
    expect(() =>
      parseMarkdownToSegments("This has **unclosed bold")
    ).not.toThrow();
    expect(() =>
      parseMarkdownToSegments("This has __unclosed bold")
    ).not.toThrow();
  });

  test("handles empty or null input", () => {
    expect(parseMarkdownToSegments("")).toEqual([]);
    expect(parseMarkdownToSegments(" ")).toEqual([
      { type: "text", text: " ", raw: " ", length: 1 },
    ]);
    expect(parseMarkdownToSegments("\n")).toEqual([
      { type: "text", text: "\n", raw: "\n", length: 1 },
    ]);
  });

  test("handles extremely long input without crashing", () => {
    const longText = "This is *italic* ".repeat(1000);
    expect(() => parseMarkdownToSegments(longText)).not.toThrow();
  });
});
