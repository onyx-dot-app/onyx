import type { Element, Root, RootContent } from "hast";

/** The streaming cursor's look. `BlinkingBar` renders the same element. */
export const STREAMING_CURSOR_CLASS_NAME =
  "animate-pulse motion-reduce:animate-none flex-none bg-text-04 rounded-xs relative top-[0.2rem] inline-block w-1.5 h-3.5";

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

function cursor(): Element {
  return {
    type: "element",
    tagName: "span",
    properties: {
      ariaHidden: "true",
      className: [STREAMING_CURSOR_CLASS_NAME, "ms-1"],
    },
    children: [],
  };
}

// Inserts the cursor after the last visible content in `children`.
function insertCursor(children: RootContent[]): void {
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
      insertCursor(child.children);
      return;
    }
    children.splice(i + 1, 0, cursor());
    return;
  }
  children.push(cursor());
}

// Rehype plugin: put the streaming cursor inline after the last character.
// Run it last, after the plugins that build the tree it walks.
export function rehypeStreamingCursor() {
  return (tree: Root) => insertCursor(tree.children);
}
