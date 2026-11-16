import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkRehype from "remark-rehype";
import rehypeKatex from "rehype-katex";
import type { Element, Root, RootContent } from "hast";
import {
  createCitationResolver,
  tableToCopyContent,
} from "@/app/app/message/tableCopyUtils";
import { OnyxDocument } from "@/lib/search/types";

function findTable(nodes: RootContent[]): Element | null {
  for (const node of nodes) {
    if (node.type !== "element") continue;
    if (node.tagName === "table") return node;
    const found = findTable(node.children);
    if (found) return found;
  }
  return null;
}

function parseTable(markdown: string): Element {
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath, { singleDollarTextMath: true })
    .use(remarkRehype)
    .use(rehypeKatex);
  const tree: Root = processor.runSync(processor.parse(markdown));
  const table = findTable(tree.children);
  if (!table) throw new Error("no table in markdown");
  return table;
}

const docs = [
  {
    document_id: "doc-1",
    semantic_identifier: "Quarterly Revenue Report 2026",
    link: "https://docs.example.com/revenue?id=7",
  },
] as OnyxDocument[];

const resolveCitation = createCitationResolver(docs, { 1: "doc-1" });

describe("tableToCopyContent", () => {
  it("keeps every row and column", () => {
    const table = parseTable(
      [
        "| Name | Role | Team |",
        "| --- | --- | --- |",
        "| Ada | Engineer | Core |",
        "| Lin | Designer | Web |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(tsv).toBe(
      "Name\tRole\tTeam\nAda\tEngineer\tCore\nLin\tDesigner\tWeb"
    );
    expect(html).toBe(
      "<table><thead><tr><th>Name</th><th>Role</th><th>Team</th></tr></thead>" +
        "<tbody><tr><td>Ada</td><td>Engineer</td><td>Core</td></tr>" +
        "<tr><td>Lin</td><td>Designer</td><td>Web</td></tr></tbody></table>"
    );
  });

  it("keeps link hrefs in HTML and writes text (url) in TSV", () => {
    const table = parseTable(
      [
        "| Tool | Site |",
        "| --- | --- |",
        "| Onyx | [Home](https://onyx.app/home) |",
        "| Bare | https://example.com |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(html).toContain('<a href="https://onyx.app/home">Home</a>');
    expect(html).toContain(
      '<a href="https://example.com">https://example.com</a>'
    );
    expect(tsv).toContain("Onyx\tHome (https://onyx.app/home)");
    expect(tsv).toContain("Bare\thttps://example.com");
  });

  it("writes the full source name for citations and drops unknown ones", () => {
    const table = parseTable(
      [
        "| Metric | Source |",
        "| --- | --- |",
        "| Revenue | [[1]](https://docs.example.com/revenue?id=7) [[9]](https://x.example.com) |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(html).toContain(
      '<a href="https://docs.example.com/revenue?id=7">Quarterly Revenue Report 2026</a>'
    );
    expect(html).not.toContain("[1]");
    expect(html).not.toContain("x.example.com");
    expect(tsv).toBe(
      "Metric\tSource\n" +
        "Revenue\tQuarterly Revenue Report 2026 (https://docs.example.com/revenue?id=7)"
    );
  });

  it("drops app-relative and unsafe hrefs but keeps the text", () => {
    const table = parseTable(
      [
        "| File |",
        "| --- |",
        "| [notes.pdf](/api/chat/file/abc) |",
        "| [bad](javascript:alert(1)) |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(html).not.toContain("href");
    expect(tsv).toBe("File\nnotes.pdf\nbad");
  });

  it("escapes HTML, keeps emphasis, and copies TeX for math", () => {
    const table = parseTable(
      [
        "| Value | Formula |",
        "| --- | --- |",
        "| **<b>bold</b>** & more | $x^2$ |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(html).toContain("<strong>");
    expect(html).toContain("&amp; more");
    expect(html).not.toContain("<b>");
    expect(tsv).toContain("\tx^2");
  });

  it("copies image alt text for standalone and linked images", () => {
    const table = parseTable(
      [
        "| Logo | Linked |",
        "| --- | --- |",
        "| ![Onyx logo](https://onyx.app/logo.png) | [![Docs badge](https://onyx.app/badge.svg)](https://docs.onyx.app) |",
        "| ![Inline chart](data:image/png;base64,AAAA) | [![Local](/api/chat/file/img)](/api/chat/file/img) |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(tsv).toBe(
      "Logo\tLinked\n" +
        "Onyx logo\tDocs badge (https://docs.onyx.app)\n" +
        "Inline chart\tLocal"
    );
    expect(html).toContain("<td>Onyx logo</td>");
    expect(html).toContain('<a href="https://docs.onyx.app">Docs badge</a>');
    expect(html).not.toContain("<img");
    expect(html).not.toContain("data:");
    expect(html).not.toContain("/api/chat/file");
  });

  it("treats a linked image with citation-like alt text as a link", () => {
    const table = parseTable(
      [
        "| Figure |",
        "| --- |",
        "| [![[1]](https://onyx.app/fig.png)](https://onyx.app/figures) |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(tsv).toBe("Figure\n[1] (https://onyx.app/figures)");
    expect(html).toContain('<a href="https://onyx.app/figures">[1]</a>');
    expect(html).not.toContain("Quarterly Revenue Report 2026");
  });

  it("copies a linked formula once, as its TeX source", () => {
    const table = parseTable(
      [
        "| Formula | Mixed |",
        "| --- | --- |",
        "| [$x^2$](https://example.com/x) | [**Area** $a+b$](https://example.com/a) |",
      ].join("\n")
    );

    const { html, tsv } = tableToCopyContent(table, resolveCitation);

    expect(tsv).toBe(
      "Formula\tMixed\n" +
        "x^2 (https://example.com/x)\tArea a+b (https://example.com/a)"
    );
    expect(html).toContain('<a href="https://example.com/x">x^2</a>');
    expect(html).toContain(
      '<a href="https://example.com/a"><strong>Area</strong> a+b</a>'
    );
  });
});
