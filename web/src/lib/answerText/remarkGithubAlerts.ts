// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

/** The few mdast fields the answer's remark plugins read and write. */
export interface MarkdownAstNode {
  type: string;
  value?: string;
  data?: {
    hName?: string;
    hProperties?: Record<string, string | boolean>;
    hChildren?: { type: "text"; value: string }[];
  };
  children?: MarkdownAstNode[];
}

const GITHUB_ALERT_MARKER =
  /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:\r?\n|$)/i;

function readGithubAlert(node: MarkdownAstNode): void {
  if (node.type !== "blockquote") return;
  const paragraph = node.children?.[0];
  const text = paragraph?.children?.[0];
  if (
    paragraph?.type !== "paragraph" ||
    text?.type !== "text" ||
    text.value === undefined
  ) {
    return;
  }
  const match = GITHUB_ALERT_MARKER.exec(text.value);
  const kind = match?.[1];
  if (!match || !kind) return;

  const remainder = text.value.slice(match[0].length);
  // A marker with more inline content on its line, like "[!NOTE] **x**", is text.
  const markerEndsItsLine = match[0].endsWith("\n");
  if (remainder.length > 0) {
    text.value = remainder;
  } else if (markerEndsItsLine || paragraph.children?.length === 1) {
    paragraph.children?.shift();
    if (paragraph.children?.length === 0) node.children?.shift();
  } else {
    return;
  }

  node.data = {
    ...node.data,
    hProperties: { ...node.data?.hProperties, dataAlert: kind.toLowerCase() },
  };
}

/** Marks a GitHub alert (`> [!NOTE]`) with `data-alert` and drops the marker. */
export function remarkGithubAlerts() {
  return (tree: MarkdownAstNode) => {
    const visit = (node: MarkdownAstNode) => {
      node.children?.forEach(visit);
      readGithubAlert(node);
    };
    visit(tree);
  };
}
