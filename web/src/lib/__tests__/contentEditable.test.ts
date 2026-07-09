/**
 * @jest-environment jsdom
 */

import {
  getTextContent,
  deleteTokenBeforeCursor,
  stripLeadingBr,
} from "@/lib/contentEditable";
import {
  shouldCreatePasteTile,
  getPasteTilePreview,
  getPasteTileMeta,
  createRichInputTileNode,
  PASTE_TILE_THRESHOLD_CHARS,
} from "@/lib/richInputTile";

describe("shouldCreatePasteTile", () => {
  it("returns false for empty string", () => {
    expect(shouldCreatePasteTile("")).toBe(false);
  });

  it("returns false for short text", () => {
    expect(shouldCreatePasteTile("hello")).toBe(false);
  });

  it("returns false for exactly 200 chars", () => {
    const text = "a".repeat(PASTE_TILE_THRESHOLD_CHARS);
    expect(text.length).toBe(200);
    expect(shouldCreatePasteTile(text)).toBe(false);
  });

  it("returns true for 201 chars", () => {
    const text = "a".repeat(PASTE_TILE_THRESHOLD_CHARS + 1);
    expect(shouldCreatePasteTile(text)).toBe(true);
  });

  it("returns false for 3 lines", () => {
    expect(shouldCreatePasteTile("a\nb\nc")).toBe(false);
  });

  it("returns true for 4 lines", () => {
    expect(shouldCreatePasteTile("a\nb\nc\nd")).toBe(true);
  });

  it("returns true when chars exceed threshold even with a single line", () => {
    const text = "a".repeat(PASTE_TILE_THRESHOLD_CHARS + 1);
    expect(text.split("\n").length).toBe(1);
    expect(shouldCreatePasteTile(text)).toBe(true);
  });
});

describe("getPasteTilePreview", () => {
  it("returns short first line as-is", () => {
    expect(getPasteTilePreview("hello")).toBe("hello");
  });

  it("returns first line at exactly maxLength without truncation", () => {
    const text = "a".repeat(18);
    expect(getPasteTilePreview(text)).toBe(text);
  });

  it("truncates first line longer than maxLength", () => {
    const text = "a".repeat(19);
    expect(getPasteTilePreview(text)).toBe("a".repeat(18) + "…");
  });

  it("uses only the first line of multiline input", () => {
    expect(getPasteTilePreview("first\nsecond\nthird")).toBe("first");
  });

  it("returns empty string for empty input", () => {
    expect(getPasteTilePreview("")).toBe("");
  });

  it("trims whitespace from first line", () => {
    expect(getPasteTilePreview("   spaced   ")).toBe("spaced");
  });

  it("respects custom maxLength parameter", () => {
    expect(getPasteTilePreview("abcdefghij", 5)).toBe("abcde…");
  });

  it("does not truncate when first line equals custom maxLength", () => {
    expect(getPasteTilePreview("abcde", 5)).toBe("abcde");
  });
});

describe("getPasteTileMeta", () => {
  it("returns chars format for single line", () => {
    expect(getPasteTileMeta("hello")).toBe("5 chars");
  });

  it("returns lines format for multiple lines", () => {
    expect(getPasteTileMeta("a\nb\nc")).toBe("3 lines");
  });

  it("returns '0 chars' for empty string", () => {
    expect(getPasteTileMeta("")).toBe("0 chars");
  });

  it("returns '2 lines' for two lines", () => {
    expect(getPasteTileMeta("line1\nline2")).toBe("2 lines");
  });
});

describe("getTextContent", () => {
  it("extracts text from a text node", () => {
    const el = document.createElement("div");
    el.appendChild(document.createTextNode("hello"));
    expect(getTextContent(el)).toBe("hello");
  });

  it("converts BR to newline", () => {
    const el = document.createElement("div");
    el.appendChild(document.createTextNode("before"));
    el.appendChild(document.createElement("br"));
    el.appendChild(document.createTextNode("after"));
    expect(getTextContent(el)).toBe("before\nafter");
  });

  it("prepends newline for block element after first child", () => {
    const el = document.createElement("div");
    el.appendChild(document.createTextNode("first"));
    const block = document.createElement("div");
    block.appendChild(document.createTextNode("second"));
    el.appendChild(block);
    expect(getTextContent(el)).toBe("first\nsecond");
  });

  it("does not prepend newline for block element as first child", () => {
    const el = document.createElement("div");
    const block = document.createElement("div");
    block.appendChild(document.createTextNode("only"));
    el.appendChild(block);
    expect(getTextContent(el)).toBe("only");
  });

  it("extracts data-text from data-rich-tile element", () => {
    const el = document.createElement("div");
    const tile = document.createElement("span");
    tile.setAttribute("data-rich-tile", "");
    tile.setAttribute("data-text", "pasted content here");
    el.appendChild(tile);
    expect(getTextContent(el)).toBe("pasted content here");
  });

  it("concatenates text, tile, and text correctly", () => {
    const el = document.createElement("div");
    el.appendChild(document.createTextNode("before "));
    const tile = document.createElement("span");
    tile.setAttribute("data-rich-tile", "");
    tile.setAttribute("data-text", "TILE");
    el.appendChild(tile);
    el.appendChild(document.createTextNode(" after"));
    expect(getTextContent(el)).toBe("before TILE after");
  });

  it("handles nested elements recursively", () => {
    const el = document.createElement("div");
    const inner = document.createElement("span");
    inner.appendChild(document.createTextNode("nested"));
    el.appendChild(inner);
    expect(getTextContent(el)).toBe("nested");
  });

  it("handles empty element", () => {
    const el = document.createElement("div");
    expect(getTextContent(el)).toBe("");
  });

  it("handles multiple block elements with newlines", () => {
    const el = document.createElement("div");
    const p1 = document.createElement("p");
    p1.appendChild(document.createTextNode("line1"));
    const p2 = document.createElement("p");
    p2.appendChild(document.createTextNode("line2"));
    const p3 = document.createElement("p");
    p3.appendChild(document.createTextNode("line3"));
    el.appendChild(p1);
    el.appendChild(p2);
    el.appendChild(p3);
    expect(getTextContent(el)).toBe("line1\nline2\nline3");
  });
});

describe("createRichInputTileNode — skill tiles", () => {
  // Skill tiles are built with a "Skill: <name>" preview and an empty meta.
  it("marks the tile type and stores the skill slug", () => {
    const tile = createRichInputTileNode({
      type: "skill",
      text: "/pptx ",
      preview: "Skill: Slides",
      meta: "",
      skillSlug: "pptx",
    });
    expect(tile.getAttribute("data-tile-type")).toBe("skill");
    expect(tile.getAttribute("data-skill-slug")).toBe("pptx");
  });

  it("serializes to the legacy `/<slug> ` literal via getTextContent", () => {
    // This is the contract that keeps the submitted payload identical to the
    // pre-tile behavior, so the backend needs no changes.
    const el = document.createElement("div");
    el.appendChild(document.createTextNode("make me "));
    el.appendChild(
      createRichInputTileNode({
        type: "skill",
        text: "/pptx ",
        preview: "Skill: Slides",
        meta: "",
        skillSlug: "pptx",
      })
    );
    el.appendChild(document.createTextNode("about cats"));
    expect(getTextContent(el)).toBe("make me /pptx about cats");
  });

  it("renders the 'Skill: <name>' preview and omits the meta when empty", () => {
    const tile = createRichInputTileNode({
      type: "skill",
      text: "/pptx ",
      preview: "Skill: Slides",
      meta: "",
      skillSlug: "pptx",
    });
    expect(tile.querySelector(".rich-input-tile-preview")?.textContent).toBe(
      "Skill: Slides"
    );
    expect(tile.querySelector(".rich-input-tile-meta")).toBeNull();
  });
});

// Caret/selection helpers — only the text-node fast paths are exercised here;
// the Selection.modify node-boundary fallback isn't implemented by jsdom and is
// left to e2e (the helpers guard on `typeof sel.modify !== "function"`).
function caretAt(node: Node, offset: number): void {
  const sel = window.getSelection()!;
  const r = document.createRange();
  r.setStart(node, offset);
  r.collapse(true);
  sel.removeAllRanges();
  sel.addRange(r);
}

function mount(html: string): HTMLDivElement {
  const el = document.createElement("div");
  el.contentEditable = "true";
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

describe("deleteTokenBeforeCursor", () => {
  it("removes the exact token before the caret and returns true", () => {
    const el = mount("hi /pptx");
    const text = el.firstChild as Text;
    caretAt(text, text.length);
    expect(deleteTokenBeforeCursor(el, "/pptx")).toBe(true);
    expect(getTextContent(el)).toBe("hi ");
    el.remove();
  });

  it("returns false (and deletes nothing) when the chars don't match", () => {
    const el = mount("hello");
    const text = el.firstChild as Text;
    caretAt(text, text.length);
    expect(deleteTokenBeforeCursor(el, "/x")).toBe(false);
    expect(getTextContent(el)).toBe("hello");
    el.remove();
  });

  it("returns false for an empty token", () => {
    const el = mount("hi");
    caretAt(el.firstChild as Text, 2);
    expect(deleteTokenBeforeCursor(el, "")).toBe(false);
    el.remove();
  });

  it("returns false when fewer chars than the token precede the caret", () => {
    const el = mount("/x");
    caretAt(el.firstChild as Text, 1);
    expect(deleteTokenBeforeCursor(el, "/x")).toBe(false);
    expect(getTextContent(el)).toBe("/x");
    el.remove();
  });

  it("returns false (no mutation) for a non-collapsed selection", () => {
    const el = mount("hi /pptx");
    const text = el.firstChild as Text;
    const sel = window.getSelection()!;
    const r = document.createRange();
    r.setStart(text, 3);
    r.setEnd(text, text.length);
    sel.removeAllRanges();
    sel.addRange(r);
    expect(deleteTokenBeforeCursor(el, "/pptx")).toBe(false);
    expect(getTextContent(el)).toBe("hi /pptx");
    el.remove();
  });

  it("returns false when the caret is outside the element", () => {
    const el = mount("hi /pptx");
    const outside = mount("/pptx");
    caretAt(outside.firstChild as Text, 5);
    expect(deleteTokenBeforeCursor(el, "/pptx")).toBe(false);
    expect(getTextContent(el)).toBe("hi /pptx");
    el.remove();
    outside.remove();
  });
});

describe("stripLeadingBr", () => {
  function tileHtml(): string {
    return '<span data-rich-tile data-tile-type="skill">Skill: X</span>';
  }

  it("removes a leading <br> that precedes a rich tile", () => {
    const el = mount(`<br>${tileHtml()}`);
    expect(stripLeadingBr(el)).toBe(true);
    expect(el.firstChild?.nodeName).toBe("SPAN");
    el.remove();
  });

  it("leaves a leading <br> that precedes text (user newline) untouched", () => {
    const el = mount("<br>hello");
    expect(stripLeadingBr(el)).toBe(false);
    expect(el.firstChild?.nodeName).toBe("BR");
    el.remove();
  });

  it("returns false when the first child is not a <br>", () => {
    const el = mount(`${tileHtml()}`);
    expect(stripLeadingBr(el)).toBe(false);
    el.remove();
  });

  it("leaves a leading <br> that precedes a non-tile element untouched", () => {
    const el = mount("<br><span>text</span>");
    expect(stripLeadingBr(el)).toBe(false);
    expect(el.firstChild?.nodeName).toBe("BR");
    el.remove();
  });
});
