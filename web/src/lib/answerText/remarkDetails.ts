import type { MarkdownAstNode } from "@/lib/answerText/remarkGithubAlerts";

const DETAILS_TOKEN =
  /<details\b[^>]*>|<summary>[\s\S]*?<\/summary>|<\/details>/gi;
const DETAILS_OPEN = /^<details(\s+open)?\s*>$/i;
// Any opener, also one with other attributes: it stays raw HTML, but its
// closing tag must not end an outer disclosure.
const ANY_DETAILS_OPEN = /^<details\b[^>]*>$/i;
const SUMMARY = /^<summary>([\s\S]*?)<\/summary>$/i;
const PARTIAL_SUMMARY = /^<summary>([\s\S]*)$/i;
const DETAILS_TAGS = ["<details>", "</details>", "<summary>"];
const NO_SUMMARY: [string, string] = ["", ""];

/** A details tag the stream has not finished, such as `<summ` or `</det`. */
function isUnfinishedTag(value: string): boolean {
  const tag = value.toLowerCase();
  return (
    tag.startsWith("<") &&
    DETAILS_TAGS.some(
      (full) => full.length > tag.length && full.startsWith(tag)
    )
  );
}
const DETAILS_CLOSE = /^<\/details>$/i;
// Tags inside these regions are text, so a block that holds one stays whole.
const RAW_TEXT_REGION = /<(?:pre|script|style|textarea)\b|<!--/i;
const NAMED_REFERENCES = new Map([
  ["amp", "&"],
  ["lt", "<"],
  ["gt", ">"],
  ["quot", '"'],
  ["apos", "'"],
  ["nbsp", "\u00a0"],
]);

function decodeReferences(text: string): string {
  return text.replace(
    /&(?:#(\d+)|#x([\da-f]+)|([a-z]+));/gi,
    (match, decimal?: string, hex?: string, name?: string) => {
      const code = decimal
        ? Number(decimal)
        : hex
          ? Number.parseInt(hex, 16)
          : undefined;
      if (code !== undefined) {
        return code > 0 && code <= 0x10ffff
          ? String.fromCodePoint(code)
          : match;
      }
      return NAMED_REFERENCES.get(name?.toLowerCase() ?? "") ?? match;
    }
  );
}

function htmlValue(node: MarkdownAstNode | undefined): string {
  return node?.type === "html" ? (node.value ?? "").trim() : "";
}

/**
 * Splits an HTML block into one node per details tag. Markdown keeps lines
 * up to the next blank line in one HTML block, so a summary and its first
 * body line, or two closing tags, can share a node. Text between tags
 * becomes a plain paragraph; other HTML stays raw.
 */
function splitDetailsTags(node: MarkdownAstNode): MarkdownAstNode[] {
  const value = node.type === "html" ? (node.value ?? "") : "";
  if (!/<\/?(?:details|summary)\b/i.test(value) || RAW_TEXT_REGION.test(value))
    return [node];
  const out: MarkdownAstNode[] = [];
  const pushSegment = (segment: string) => {
    const text = segment.trim();
    if (!text) return;
    out.push(
      text.includes("<")
        ? { type: "html", value: text }
        : { type: "paragraph", children: [{ type: "text", value: text }] }
    );
  };
  let last = 0;
  for (const match of value.matchAll(DETAILS_TOKEN)) {
    pushSegment(value.slice(last, match.index));
    out.push({ type: "html", value: match[0] });
    last = match.index + match[0].length;
  }
  pushSegment(value.slice(last));
  return out;
}

function groupDetails(nodes: MarkdownAstNode[]): MarkdownAstNode[] {
  const out: MarkdownAstNode[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    if (!node) continue;
    const last = nodes.length - 1;
    // A streaming answer can end in a tag: it shows once the tag is whole
    if (i === last && isUnfinishedTag(htmlValue(node))) continue;
    const open = DETAILS_OPEN.exec(htmlValue(node));
    const next = htmlValue(nodes[i + 1]);
    // ...or at the opener, or inside the summary
    const summary =
      SUMMARY.exec(next) ??
      (i + 1 === last
        ? (PARTIAL_SUMMARY.exec(next) ??
          (isUnfinishedTag(next) ? NO_SUMMARY : null))
        : null) ??
      (i === last ? NO_SUMMARY : null);
    let close = -1;
    if (open && summary) {
      let depth = 1;
      for (let j = i + 2; j < nodes.length && close < 0; j++) {
        const tag = htmlValue(nodes[j]);
        if (ANY_DETAILS_OPEN.test(tag)) depth++;
        else if (DETAILS_CLOSE.test(tag) && --depth === 0) close = j;
      }
      // Unclosed, it runs to the end of its container, as in HTML, so a
      // streaming answer shows a disclosure before its closing tag arrives
      if (close < 0) close = nodes.length;
    }
    if (!open || !summary) {
      out.push(node);
      continue;
    }
    const title = decodeReferences(
      // Only real tags go; a comparison such as `x < 5 > 3` stays text.
      (summary[1] ?? "")
        .replace(/<\/?[a-z][^<>]*>/gi, "")
        // A closing tag the stream has not finished
        .replace(/<\/?[a-z]*$/i, "")
        .trim()
    );
    out.push({
      type: "details",
      data: {
        hName: "details",
        hProperties: open[1] ? { open: true } : {},
      },
      children: [
        {
          type: "detailsSummary",
          data: {
            hName: "summary",
            hChildren: [{ type: "text", value: title }],
          },
        },
        ...groupDetails(nodes.slice(i + 2, close)),
      ],
    });
    i = close;
  }
  return out;
}

/**
 * Turns `<details><summary>…</summary>` … `</details>` raw HTML around
 * markdown into a `details` element, without parsing raw HTML. Other raw
 * HTML is left alone.
 */
export function remarkDetails() {
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      if (!node.children) return;
      node.children.forEach(visit);
      node.children = groupDetails(node.children.flatMap(splitDetailsTags));
    };
    visit(tree);
  };
}
