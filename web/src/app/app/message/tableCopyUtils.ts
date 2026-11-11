import type { Element, ElementContent } from "hast";
import { CitationMap } from "@/app/app/types";
import { OnyxDocument } from "@/lib/search/types";
import { transformLinkUri } from "@/lib/utils";

export interface TableCopyContent {
  html: string;
  tsv: string;
}

export interface CopyLink {
  text: string;
  href: string | null;
}

/** Returns the full source for a citation label such as `[1]`, or null to drop it. */
export type CitationResolver = (label: string) => CopyLink | null;

interface CopyFragment {
  html: string;
  text: string;
}

const CITATION_LABEL_PATTERN = /^\[(D|Q)?(\d+)\]$/;
const KEPT_TAGS = new Set(["strong", "em", "code", "del"]);

export function createCitationResolver(
  docs: OnyxDocument[] | null | undefined,
  citations: CitationMap | undefined
): CitationResolver {
  return (label) => {
    const match = label.match(CITATION_LABEL_PATTERN);
    if (!match || match[1] === "Q" || !match[2]) return null;
    const documentId = citations?.[parseInt(match[2], 10)];
    const doc = documentId
      ? docs?.find((d) => d.document_id === documentId)
      : undefined;
    if (!doc) return null;
    return {
      text: doc.semantic_identifier || doc.link || label,
      href: doc.link || null,
    };
  };
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Absolute http(s)/mailto links only: app-relative links do not work outside Onyx. */
function copyableHref(href: string | null): string | null {
  if (!href) return null;
  const safe = transformLinkUri(href);
  if (!safe) return null;
  try {
    new URL(safe);
    return safe;
  } catch {
    return null;
  }
}

function hasClass(node: Element, name: string): boolean {
  const className = node.properties?.className;
  return Array.isArray(className) && className.includes(name);
}

function findTexSource(node: Element): string | null {
  for (const child of node.children) {
    if (child.type !== "element") continue;
    if (child.tagName === "annotation") return plainText(child);
    const found = findTexSource(child);
    if (found !== null) return found;
  }
  return null;
}

function plainText(node: ElementContent): string {
  if (node.type === "text") return node.value;
  if (node.type !== "element") return "";
  return node.children.map(plainText).join("");
}

function linkFragment(link: CopyLink): CopyFragment {
  const href = copyableHref(link.href);
  if (!href) {
    return { html: escapeHtml(link.text), text: link.text };
  }
  return {
    html: `<a href="${escapeHtml(href)}">${escapeHtml(link.text)}</a>`,
    text: link.text === href ? href : `${link.text} (${href})`,
  };
}

function joinFragments(fragments: CopyFragment[]): CopyFragment {
  return {
    html: fragments.map((f) => f.html).join(""),
    text: fragments.map((f) => f.text).join(""),
  };
}

function contentFragment(
  node: ElementContent,
  resolveCitation: CitationResolver
): CopyFragment {
  if (node.type === "text") {
    return { html: escapeHtml(node.value), text: node.value };
  }
  if (node.type !== "element") return { html: "", text: "" };

  if (node.tagName === "br") return { html: "<br>", text: " " };

  // KaTeX renders MathML and HTML copies of each formula; copy the TeX source.
  if (hasClass(node, "katex")) {
    const tex = findTexSource(node) ?? "";
    return { html: escapeHtml(tex), text: tex };
  }

  if (node.tagName === "a") {
    const label = plainText(node);
    if (CITATION_LABEL_PATTERN.test(label.trim())) {
      const source = resolveCitation(label.trim());
      return source ? linkFragment(source) : { html: "", text: "" };
    }
    const href = node.properties?.href;
    return linkFragment({
      text: label,
      href: typeof href === "string" ? href : null,
    });
  }

  const inner = joinFragments(
    node.children.map((child) => contentFragment(child, resolveCitation))
  );
  if (KEPT_TAGS.has(node.tagName)) {
    return {
      html: `<${node.tagName}>${inner.html}</${node.tagName}>`,
      text: inner.text,
    };
  }
  return inner;
}

function childElements(node: Element, tagNames: string[]): Element[] {
  return node.children.filter(
    (child): child is Element =>
      child.type === "element" && tagNames.includes(child.tagName)
  );
}

function tsvCell(text: string): string {
  return text.replace(/[\t\r\n]+/g, " ").trim();
}

/** Builds a clean HTML table and TSV text from a rendered markdown table. */
export function tableToCopyContent(
  table: Element,
  resolveCitation: CitationResolver
): TableCopyContent {
  const htmlSections: string[] = [];
  const tsvRows: string[] = [];

  const sections = childElements(table, ["thead", "tbody", "tfoot"]);
  for (const section of sections.length > 0 ? sections : [table]) {
    const htmlRows = childElements(section, ["tr"]).map((row) => {
      const cells = childElements(row, ["th", "td"]).map((cell) => ({
        tag: cell.tagName,
        fragment: joinFragments(
          cell.children.map((child) => contentFragment(child, resolveCitation))
        ),
      }));
      tsvRows.push(cells.map((c) => tsvCell(c.fragment.text)).join("\t"));
      return `<tr>${cells
        .map((c) => `<${c.tag}>${c.fragment.html.trim()}</${c.tag}>`)
        .join("")}</tr>`;
    });
    htmlSections.push(
      section === table
        ? htmlRows.join("")
        : `<${section.tagName}>${htmlRows.join("")}</${section.tagName}>`
    );
  }

  return {
    html: `<table>${htmlSections.join("")}</table>`,
    tsv: tsvRows.join("\n"),
  };
}
