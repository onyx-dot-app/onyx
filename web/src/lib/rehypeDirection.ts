import type { Element, ElementContent, Root } from "hast";

// Blocks get an explicit direction so mixed RTL/LTR messages align per
// block. dir="auto" fails on loose-list li (their inline p carries dir,
// which the auto algorithm skips), so the direction is computed here.
const DIRECTIONAL_TAGS = new Set([
  "p",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "ul",
  "ol",
  "li",
  "blockquote",
  "table",
]);

// Code is always LTR and often leads an RTL sentence, so it must not
// influence the direction of the block containing it.
const OPAQUE_TAGS = new Set(["code", "pre"]);

// Strong RTL letters from every right-to-left script, plus the RLM and ALM
// marks. Script-based, so any RTL language matches. Digits and punctuation
// are weak and skipped, mirroring browsers' first-strong dir="auto".
const RTL_MARK = /[\u200F\u061C]/u;
const RTL_SCRIPT =
  /[\p{Script=Arabic}\p{Script=Hebrew}\p{Script=Syriac}\p{Script=Thaana}\p{Script=Nko}\p{Script=Samaritan}\p{Script=Mandaic}\p{Script=Adlam}]/u;
const ANY_LETTER = /\p{L}/u;

function firstStrongDir(nodes: ElementContent[]): "ltr" | "rtl" | null {
  for (const node of nodes) {
    if (node.type === "text") {
      for (const char of node.value) {
        if (RTL_MARK.test(char)) return "rtl";
        // Only letters are strong. Arabic-Indic digits sit in Script=Arabic
        // but are directionally weak, so they must not decide direction.
        if (!ANY_LETTER.test(char)) continue;
        return RTL_SCRIPT.test(char) ? "rtl" : "ltr";
      }
    } else if (node.type === "element" && !OPAQUE_TAGS.has(node.tagName)) {
      const dir = firstStrongDir(node.children);
      if (dir) return dir;
    }
  }
  return null;
}

function stampDir(node: Root | Element): void {
  if (node.type === "element") {
    if (node.tagName === "pre") {
      node.properties = { ...node.properties, dir: "ltr" };
    } else if (DIRECTIONAL_TAGS.has(node.tagName)) {
      const dir = firstStrongDir(node.children);
      // No letters at all (bare numbers, emoji): leave it to inherit from
      // the surrounding dir="auto" message container.
      if (dir) {
        node.properties = { ...node.properties, dir };
      }
    }
  }
  for (const child of node.children) {
    if (child.type === "element") {
      stampDir(child);
    }
  }
}

// Rehype plugin: stamp each block with the direction of its first strong
// character and pin `pre` to LTR. Component maps that intercept these
// tags must forward `dir` (MemoizedParagraph and CodeBlock do).
export function rehypeDirection() {
  return (tree: Root) => stampDir(tree);
}
