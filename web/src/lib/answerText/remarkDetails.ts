import type { MarkdownAstNode } from "@/lib/answerText/remarkGithubAlerts";

const DETAILS_OPEN =
  /^<details(\s+open)?\s*>\s*<summary>([\s\S]*?)<\/summary>\s*$/i;
const DETAILS_CLOSE = /^<\/details>\s*$/i;

function isOpen(node: MarkdownAstNode): RegExpExecArray | null {
  return node.type === "html" ? DETAILS_OPEN.exec(node.value ?? "") : null;
}

function isClose(node: MarkdownAstNode): boolean {
  return node.type === "html" && DETAILS_CLOSE.test(node.value ?? "");
}

function groupDetails(nodes: MarkdownAstNode[]): MarkdownAstNode[] {
  const out: MarkdownAstNode[] = [];
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i];
    if (!node) continue;
    const open = isOpen(node);
    let close = -1;
    if (open) {
      let depth = 1;
      for (let j = i + 1; j < nodes.length && close < 0; j++) {
        const next = nodes[j];
        if (!next) continue;
        if (isOpen(next)) depth++;
        else if (isClose(next) && --depth === 0) close = j;
      }
    }
    if (!open || close < 0) {
      out.push(node);
      continue;
    }
    const summary = (open[2] ?? "").replace(/<[^>]*>/g, "").trim();
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
            hChildren: [{ type: "text", value: summary }],
          },
        },
        ...groupDetails(nodes.slice(i + 1, close)),
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
      node.children = groupDetails(node.children);
    };
    visit(tree);
  };
}
