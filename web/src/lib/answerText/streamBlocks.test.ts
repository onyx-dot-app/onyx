import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import {
  endsInOpenCodeFence,
  splitMarkdownBlocks,
} from "@/lib/answerText/streamBlocks";

describe("endsInOpenCodeFence", () => {
  it.each([
    ["text", false],
    ["```py\nx = 1", true],
    ["```py\nx = 1\n```", false],
    ["```py\nx = 1\n```\n\nmore", false],
    ["~~~\n```\nstill code", true],
    ["````\n```\n````", false],
    ["- item\n\n  ```\n  code", true],
    ["```a``` is inline", false],
    ["  ```python\nx = 1", true],
    ["   ~~~\ncode\n less indented", true],
    ["- item\n\n  ```python\n  x\n\nMore text", false],
    ["1. item\n\n  ```python\nx = 1", true],
    ["> ```\n> x\nplain", false],
    ["> ```\n> x\n>\n> more code", true],
    ["- ```\n  x\n```\nnew fence", true],
    ["- ```\n  x\n  ```\n\nafter", false],
  ])("%j: %s", (text, open) => {
    expect(endsInOpenCodeFence(text)).toBe(open);
  });
});

// Whitespace between top-level blocks collapses in the rendered answer.
function html(source: string): string {
  return renderToStaticMarkup(
    createElement(
      ReactMarkdown,
      {
        remarkPlugins: [
          remarkGfm,
          [remarkMath, { singleDollarTextMath: false }],
        ],
      },
      source
    )
  )
    .replace(/>\s+</g, "><")
    .trim();
}

describe("splitMarkdownBlocks", () => {
  it.each([
    "# Title\n\nFirst paragraph with `code` and **bold**.\n\nSecond [link](https://example.com).",
    "# Setup\n\n# Setup\n\nText",
    "- one\n- two\n\n- loose three\n\n  continued\n\nAfter the list.",
    "1. first\n\n2. second\n\nText\n\n3) restarted",
    "```ts\nconst a = 1;\n\n\nconst b = 2;\n```\n\nafter\n\n~~~\nx\n\n~~~~\n\ny\n~~~\n\nend",
    "> quote\n\n> another quote\n\n> [!NOTE]\n> alert",
    "| a | b |\n| - | - |\n| 1 | 2 |\n\nAfter the table.",
    "para\n\n    indented code\n\nnext",
    "Setext\n===\n\nnext\n---\n\n- [ ] task\n- [x] done",
    "- a\n\n  ```\n  x\n\n```\n\nb",
    "- a\n\n  ```\n  x\n\ny\n\n  ```\n\nb",
    "```a``` is inline.\n\nprose\n\n```\none\n\ntwo\n```\n\nafter",
    "intro\n\n$$\na\n\nb\n$$\n\nafter $$x$$ inline\n\n$$ y $$\n\nend",
    "intro\n\n$$$$\na\n\n$$\n\nb\n$$$$\n\nend",
    "$$\nx$$\n\ny\n$$\n\nend",
    "$$\na\n\nb $$ c\n  $$  \n\nend",
    "$$a$b\n\nc",
    "[guide][a\\]b]\n\n[a\\]b]: https://example.com\n\nend",
    "[ref]\n\n> [ref]: https://example.com\n\nend",
    "[ref]\n\n- item\n\n  [ref]: https://example.com\n\nend",
    "[multi line]\n\n[multi\nline]: https://example.com\n\nend",
    "**a\n\u00a0\nb**",
  ])(
    "renders each block as the whole text renders it, at every streamed prefix: %j",
    (text) => {
      for (let end = 0; end <= text.length; end++) {
        const source = text.slice(0, end);
        const blocks = splitMarkdownBlocks(source) ?? [source];
        expect(blocks.join("")).toBe(source);
        expect(blocks.map(html).join("")).toBe(html(source));
      }
    }
  );

  it("splits only between closed blocks", () => {
    expect(
      splitMarkdownBlocks("a\n\n```\nb\n\nc\n```\n\n- d\n\n- e\n\nf")
    ).toEqual(["a\n\n", "```\nb\n\nc\n```\n\n- d\n\n- e\n\n", "f"]);
    expect(splitMarkdownBlocks("a\n\n---\n\nb")).toEqual([
      "a\n\n",
      "---\n\n",
      "b",
    ]);
  });

  it("keeps a fenced code block with blank lines in one block", () => {
    expect(splitMarkdownBlocks("```\none\n\n\ntwo\n```\n\nafter")).toEqual([
      "```\none\n\n\ntwo\n```\n\n",
      "after",
    ]);
  });

  it("keeps display math with blank lines in one block", () => {
    expect(splitMarkdownBlocks("a\n\n$$\nx\n\ny\n$$\n\nb")).toEqual([
      "a\n\n",
      "$$\nx\n\ny\n$$\n\n",
      "b",
    ]);
    expect(splitMarkdownBlocks("$$ x $$\n\nb")).toEqual(["$$ x $$\n\n", "b"]);
    expect(splitMarkdownBlocks("$$$$\nx\n\n$$\n\ny\n$$$$\n\nb")).toEqual([
      "$$$$\nx\n\n$$\n\ny\n$$$$\n\n",
      "b",
    ]);
  });

  it("keeps a list continuation after a blank line in the list", () => {
    expect(splitMarkdownBlocks("- a\n\n  more of a\n- b\n\nafter")).toEqual([
      "- a\n\n  more of a\n- b\n\n",
      "after",
    ]);
  });

  it.each([
    "[ref]\n\n[x]: https://example.com",
    "[ref]\n\n> [ref]: https://example.com",
    "[ref]\n\n- [ref]: https://example.com",
    "[a b]\n\n[a\nb]: https://example.com",
    "[guide][a\\]b]\n\n[a\\]b]: https://example.com",
    "a[^x]\n\n[^x]: note",
    "<details>\n\nbody\n\n</details>",
    ":::note\n\ncontent\n\n:::",
    "a\r\n\r\nb",
    "﻿a\n\nb",
  ])("keeps text with document-wide syntax whole: %j", (text) => {
    expect(splitMarkdownBlocks(text)).toBeNull();
  });
});
