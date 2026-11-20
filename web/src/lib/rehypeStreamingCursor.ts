import type { Element, Root, RootContent } from "hast";

/** The streaming cursor's look, without its placement. */
export const STREAMING_CURSOR_LOOK =
  "animate-pulse motion-reduce:animate-none bg-text-04 rounded-xs w-1.5 h-3.5";

/** The streaming cursor inline in text. `BlinkingBar` renders the same box. */
export const STREAMING_CURSOR_CLASS_NAME = `${STREAMING_CURSOR_LOOK} flex-none relative top-[0.2rem] inline-block`;

/**
 * Marks where a response's one cursor sits (see `Response`). The marker has
 * the cursor's box but is invisible.
 */
export const RESPONSE_CURSOR_ANCHOR_ATTRIBUTE = "data-response-cursor";

export interface RehypeStreamingCursorOptions {
  /** Insert an invisible marker for the response's cursor, not a cursor. */
  anchor?: boolean;
}

// The cursor goes after these, never inside: code shows its text verbatim,
// a link would make the cursor part of it, and KaTeX output is a fixed
// layout.
const OPAQUE_TAGS = new Set(["pre", "code", "a"]);

function isOpaque(node: Element): boolean {
  if (OPAQUE_TAGS.has(node.tagName)) return true;
  const className = node.properties.className;
  return (
    Array.isArray(className) &&
    className.some((name) => name === "katex" || name === "katex-display")
  );
}

function cursor(anchor: boolean): Element {
  return {
    type: "element",
    tagName: "span",
    properties: anchor
      ? {
          ariaHidden: "true",
          dataResponseCursor: "text",
          className: [STREAMING_CURSOR_CLASS_NAME, "ms-1", "invisible"],
        }
      : {
          ariaHidden: "true",
          className: [STREAMING_CURSOR_CLASS_NAME, "ms-1"],
        },
    children: [],
  };
}

// Inserts the cursor after the last visible content in `children`.
function insertCursor(children: RootContent[], anchor: boolean): void {
  for (let i = children.length - 1; i >= 0; i--) {
    const child = children[i];
    if (!child || child.type === "comment" || child.type === "doctype") {
      continue;
    }
    if (child.type === "text" && child.value.trim() === "") continue;
    if (
      child.type === "element" &&
      !isOpaque(child) &&
      child.children.length > 0
    ) {
      insertCursor(child.children, anchor);
      return;
    }
    children.splice(i + 1, 0, cursor(anchor));
    return;
  }
  children.push(cursor(anchor));
}

// Rehype plugin: put the streaming cursor inline after the last character.
// Run it last, after the plugins that build the tree it walks.
export function rehypeStreamingCursor(options?: RehypeStreamingCursorOptions) {
  const anchor = options?.anchor ?? false;
  return (tree: Root) => insertCursor(tree.children, anchor);
}
