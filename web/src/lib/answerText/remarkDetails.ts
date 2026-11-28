import type { MarkdownAstNode } from "@/lib/answerText/remarkGithubAlerts";

const DETAILS_TOKEN =
  /<details(?=[\s/>])[^>]*>|<summary>[\s\S]*?<\/summary>|<\/details>/gi;
const DETAILS_OPEN = /^<details(\s+open)?\s*>$/i;
// Any opener, also one with other attributes: it stays raw HTML, but its
// closing tag must not end an outer disclosure.
const ANY_DETAILS_OPEN = /^<details(?=[\s/>])[^>]*>$/i;
const SUMMARY = /^<summary>([\s\S]*?)<\/summary>$/i;
// A summary the stream has not closed yet
const PARTIAL_SUMMARY = /^<summary>((?:(?!<\/summary>)[\s\S])*)$/i;
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
 * A node's text when it can hold an unfinished tag: raw HTML, or a paragraph
 * of plain text, which a lone `<` after a blank line becomes.
 */
function tailValue(node: MarkdownAstNode | undefined): string {
  const only =
    node?.type === "paragraph" && node.children?.length === 1
      ? node.children[0]
      : undefined;
  return only?.type === "text" ? (only.value ?? "").trim() : htmlValue(node);
}

/** The raw HTML in an inline node, also inside formatting, in source order. */
function inlineHtml(node: MarkdownAstNode): MarkdownAstNode[] {
  return node.type === "html"
    ? [node]
    : (node.children ?? []).flatMap(inlineHtml);
}

/** A copy of `node` with `children`, or null if there are none. */
function withChildren(
  node: MarkdownAstNode,
  children: MarkdownAstNode[]
): MarkdownAstNode | null {
  return children.length > 0 ? { ...node, children } : null;
}

/**
 * Splits an inline node at `target`, which it drops. Formatting around the
 * target goes to both sides: `**a</details> b**` gives `**a**` and `** b**`.
 */
function splitAt(
  node: MarkdownAstNode,
  target: MarkdownAstNode
): [MarkdownAstNode | null, MarkdownAstNode | null] {
  const children = node.children ?? [];
  const k = children.findIndex(
    (child) => child === target || inlineHtml(child).includes(target)
  );
  const child = children[k];
  if (!child) return [node, null];
  const [head, tail] = child === target ? [null, null] : splitAt(child, target);
  return [
    withChildren(node, [...children.slice(0, k), ...(head ? [head] : [])]),
    withChildren(node, [...(tail ? [tail] : []), ...children.slice(k + 1)]),
  ];
}

/**
 * Counts the details tags inside a paragraph, such as `Step one</details>`.
 * Returns the depth after them, and the closing tag that brings `depth` to
 * zero.
 */
function scanInline(
  node: MarkdownAstNode | undefined,
  depth: number
): { depth: number; tag: MarkdownAstNode | null } {
  const children = node?.type === "paragraph" ? (node.children ?? []) : [];
  for (const html of children.flatMap(inlineHtml)) {
    const tag = htmlValue(html);
    if (ANY_DETAILS_OPEN.test(tag)) depth++;
    else if (DETAILS_CLOSE.test(tag) && --depth === 0)
      return { depth, tag: html };
  }
  return { depth, tag: null };
}

/** A paragraph of `children`, without leading space, or null if empty. */
function paragraphOf(
  node: MarkdownAstNode,
  children: MarkdownAstNode[]
): MarkdownAstNode | null {
  const [first, ...rest] = children;
  if (first?.type === "text") {
    const value = (first.value ?? "").trimStart();
    children = value ? [{ ...first, value }, ...rest] : rest;
  }
  return withChildren(node, children);
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

function groupDetails(
  input: MarkdownAstNode[],
  streaming: boolean
): MarkdownAstNode[] {
  // Text after an inline closing tag is spliced in after the disclosure
  const nodes = [...input];
  const unfinished = (node: MarkdownAstNode | undefined) =>
    streaming && isUnfinishedTag(tailValue(node));
  const out: MarkdownAstNode[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    if (!node) continue;
    const last = nodes.length - 1;
    // A streaming answer can end in a tag: it shows once the tag is whole.
    // A finished answer keeps it, as a literal sign such as `<`.
    if (i === last && unfinished(node)) continue;
    const open = DETAILS_OPEN.exec(htmlValue(node));
    const next = htmlValue(nodes[i + 1]);
    // ...or at the opener, or inside the summary
    const complete = SUMMARY.exec(next);
    const partial =
      complete === null && i + 1 === last
        ? (PARTIAL_SUMMARY.exec(next) ??
          (unfinished(nodes[i + 1]) ? NO_SUMMARY : null))
        : null;
    const summary = complete ?? partial ?? (i === last ? NO_SUMMARY : null);
    let close = -1;
    // A closing tag inside a body paragraph
    let closeTag: MarkdownAstNode | null = null;
    if (open && summary) {
      let depth = 1;
      for (let j = i + 2; j < nodes.length && close < 0; j++) {
        const tag = htmlValue(nodes[j]);
        if (ANY_DETAILS_OPEN.test(tag)) depth++;
        else if (DETAILS_CLOSE.test(tag) && --depth === 0) close = j;
        else {
          const inline = scanInline(nodes[j], depth);
          depth = inline.depth;
          if (inline.tag) {
            close = j;
            closeTag = inline.tag;
          }
        }
      }
      // Unclosed, it runs to the end of its container, as in HTML, so a
      // streaming answer shows a disclosure before its closing tag arrives
      if (close < 0) close = nodes.length;
    }
    if (!open || !summary) {
      out.push(node);
      continue;
    }
    // Only real tags go; a comparison such as `x < 5 > 3` stays text.
    let rawTitle = (summary[1] ?? "").replace(/<\/?[a-z][^<>]*>/gi, "");
    // A summary still streaming can end in a closing tag it has not finished
    if (partial !== null) rawTitle = rawTitle.replace(/<\/?[a-z]*$/i, "");
    const title = decodeReferences(rawTitle.trim());
    const closing = nodes[close];
    const body = nodes.slice(i + 2, close);
    if (closing && closeTag) {
      const [before, after] = splitAt(closing, closeTag);
      const head = before && paragraphOf(before, before.children ?? []);
      const tail = after && paragraphOf(after, after.children ?? []);
      if (head) body.push(head);
      if (tail) nodes.splice(close + 1, 0, tail);
    }
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
        ...groupDetails(body, streaming),
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
export function remarkDetails(options?: { streaming?: boolean }) {
  const streaming = options?.streaming ?? false;
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      if (!node.children) return;
      node.children.forEach(visit);
      node.children = groupDetails(
        node.children.flatMap(splitDetailsTags),
        streaming
      );
    };
    visit(tree);
  };
}
