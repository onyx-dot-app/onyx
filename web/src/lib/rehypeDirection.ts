import type { Element, ElementContent, Root } from "hast";

// Blocks get an explicit direction so mixed RTL/LTR messages align per
// block. dir="auto" fails on loose-list li (their child p carries dir,
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

// Strong letters from the scripts whose letters carry Bidi_Class R or AL
// (JS regexes cannot query Bidi_Class directly, and Garay needs Unicode 16
// engines). Digits and punctuation are weak, mirroring first-strong.
const RTL_MARK = /[\u200F\u061C]/u;
const LTR_MARK = /\u200E/u;
// Strong R and AL code points that are not letters: Hebrew and Arabic
// punctuation and signs, Syriac punctuation, NKo digits, the rial sign.
const RTL_STRONG_PUNCT =
  /[\u05BE\u05C0\u05C3\u05C6\u05F3\u05F4\u0608\u060B\u060D\u061B\u061E\u061F\u066D\u06D4\u0700-\u070D\u07C0-\u07C9\u085E\uFDFC]/u;
const RTL_SCRIPT =
  /[\p{Script=Arabic}\p{Script=Hebrew}\p{Script=Syriac}\p{Script=Thaana}\p{Script=Nko}\p{Script=Samaritan}\p{Script=Mandaic}\p{Script=Adlam}\p{Script=Hanifi_Rohingya}\p{Script=Yezidi}\p{Script=Phoenician}\p{Script=Imperial_Aramaic}\p{Script=Old_South_Arabian}\p{Script=Old_North_Arabian}\p{Script=Avestan}\p{Script=Sogdian}\p{Script=Old_Sogdian}\p{Script=Manichaean}\p{Script=Psalter_Pahlavi}\p{Script=Inscriptional_Pahlavi}\p{Script=Inscriptional_Parthian}\p{Script=Nabataean}\p{Script=Palmyrene}\p{Script=Hatran}\p{Script=Elymaic}\p{Script=Lydian}\p{Script=Kharoshthi}\p{Script=Old_Hungarian}\p{Script=Old_Turkic}\p{Script=Cypriot}\p{Script=Mende_Kikakui}\p{Script=Meroitic_Cursive}\p{Script=Meroitic_Hieroglyphs}\p{Script=Chorasmian}\p{Script=Old_Uyghur}]/u;
const ANY_LETTER = /\p{L}/u;

/** First-strong direction of plain text, or null when no letter decides. */
export function firstStrongTextDir(value: string): "ltr" | "rtl" | null {
  for (const char of value) {
    if (RTL_MARK.test(char)) return "rtl";
    if (LTR_MARK.test(char)) return "ltr";
    if (RTL_STRONG_PUNCT.test(char)) return "rtl";
    // Otherwise only letters are strong. Arabic-Indic digits sit in
    // Script=Arabic but are weak, so they must not decide direction.
    if (!ANY_LETTER.test(char)) continue;
    return RTL_SCRIPT.test(char) ? "rtl" : "ltr";
  }
  return null;
}

function firstStrongDir(nodes: ElementContent[]): "ltr" | "rtl" | null {
  for (const node of nodes) {
    if (node.type === "text") {
      const dir = firstStrongTextDir(node.value);
      if (dir) return dir;
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
      // No letters at all (bare numbers, emoji): leave the block
      // unstamped so it inherits its container's direction.
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
// tags must forward `dir`, or a dir="auto" wrapper must backstop them.
export function rehypeDirection() {
  return (tree: Root) => stampDir(tree);
}
