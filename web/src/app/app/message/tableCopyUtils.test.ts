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
});
