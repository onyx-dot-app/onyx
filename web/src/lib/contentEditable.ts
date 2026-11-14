// ─── Cursor Utilities ───────────────────────────────────────────────────────

export function setCursorToEnd(element: HTMLElement): void {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(element);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

export function setCursorAfterNode(node: Node): void {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.setStartAfter(node);
  range.setEndAfter(node);
  selection.removeAllRanges();
  selection.addRange(range);
}

export function setCursorBeforeNode(node: Node): void {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.setStartBefore(node);
  range.setEndBefore(node);
  selection.removeAllRanges();
  selection.addRange(range);
}

// Stands in for an atomic tile, so a tile's text never reads as typed text.
const TILE_PLACEHOLDER = "\uFFFC";

/** Text split at the caret: `before` ends at the caret, `after` starts there. */
export interface CaretText {
  before: string;
  after: string;
}

/** The plain text of `element` split at the caret, with each rich tile as one
 * placeholder character, or null without a caret inside it. `after` stops at
 * the first whitespace after the caret. */
export function getTextAroundCursor(element: HTMLElement): CaretText | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const { startContainer: node, startOffset: offset } = selection.getRangeAt(0);
  if (!element.contains(node)) return null;
  const read = (clipAtCaret: (range: Range) => void): string => {
    const range = document.createRange();
    range.selectNodeContents(element);
    clipAtCaret(range);
    const container = document.createElement("div");
    container.appendChild(range.cloneContents());
    container
      .querySelectorAll("[data-rich-tile]")
      .forEach((tile) => tile.replaceWith(TILE_PLACEHOLDER));
    return getTextContent(container);
  };
  // The caret's word usually ends inside its own text node, so `after` copies
  // the rest of the input only when it does not.
  const tail =
    node.nodeType === Node.TEXT_NODE
      ? (node.textContent ?? "").slice(offset)
      : "";
  const wordEnd = tail.search(/\s/);
  let after = tail.slice(0, wordEnd);
  if (wordEnd === -1) {
    const rest = read((range) => range.setStart(node, offset));
    after = rest.slice(0, rest.search(/\s|$/));
  }
  return {
    before: read((range) => range.setEnd(node, offset)),
    after,
  };
}

/** Whether the whitespace-delimited token before the caret can contain
 * `char`. Reads only the caret's text node, so callers can skip the copy that
 * `getTextAroundCursor` makes. */
export function caretTokenMayContain(
  element: HTMLElement,
  char: string
): boolean {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return false;
  const range = selection.getRangeAt(0);
  const node = range.startContainer;
  if (!element.contains(node)) return false;
  if (node.nodeType !== Node.TEXT_NODE) return true;
  const before = (node.textContent ?? "").slice(0, range.startOffset);
  const tokenStart = before.search(/\S*$/);
  if (before.slice(tokenStart).includes(char)) return true;
  // A token that reaches the node's start can continue in an earlier node.
  return (
    tokenStart === 0 &&
    (node.previousSibling !== null || node.parentNode !== element)
  );
}

/** Viewport rect of the caret, or `element`'s rect when the caret has none. */
export function getCaretRect(element: HTMLElement): DOMRect | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0).cloneRange();
  range.collapse(true);
  const rect = range.getBoundingClientRect();
  if (
    rect.top === 0 &&
    rect.left === 0 &&
    rect.width === 0 &&
    rect.height === 0
  ) {
    return element.getBoundingClientRect();
  }
  return rect;
}

// ─── Text Insertion ─────────────────────────────────────────────────────────

export function insertTextAtCursor(element: HTMLElement, text: string): string {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    element.appendChild(document.createTextNode(text));
    setCursorToEnd(element);
    element.normalize();
    return getTextContent(element);
  }

  const range = selection.getRangeAt(0);

  if (!element.contains(range.commonAncestorContainer)) {
    element.appendChild(document.createTextNode(text));
    setCursorToEnd(element);
    element.normalize();
    return getTextContent(element);
  }

  range.deleteContents();

  const textNode = document.createTextNode(text);
  range.insertNode(textNode);

  range.setStartAfter(textNode);
  range.setEndAfter(textNode);
  selection.removeAllRanges();
  selection.addRange(range);

  element.normalize();
  return getTextContent(element);
}

export function insertNodeAtCursor(element: HTMLElement, node: Node): void {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    element.appendChild(node);
    setCursorAfterNode(node);
    element.normalize();
    return;
  }

  const range = selection.getRangeAt(0);

  if (!element.contains(range.commonAncestorContainer)) {
    element.appendChild(node);
    setCursorAfterNode(node);
    element.normalize();
    return;
  }

  range.deleteContents();
  range.insertNode(node);
  setCursorAfterNode(node);
  element.normalize();
}

// ─── Undo Snapshots ─────────────────────────────────────────────────────────

/**
 * Serialized editor state for the app-level undo/redo history. Selection
 * endpoints are in "flat units" — one per text character, `<br>`, or atomic
 * rich tile — so they survive the innerHTML round-trip.
 */
export interface EditableSnapshot {
  html: string;
  selStart: number;
  selEnd: number;
}

function isAtomicNode(node: Node): boolean {
  if (node.nodeType !== Node.ELEMENT_NODE) return false;
  const el = node as HTMLElement;
  return el.tagName === "BR" || el.hasAttribute("data-rich-tile");
}

function unitLength(node: Node): number {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent?.length ?? 0;
  if (isAtomicNode(node)) return 1;
  let sum = 0;
  node.childNodes.forEach((child) => {
    sum += unitLength(child);
  });
  return sum;
}

function boundaryToFlatOffset(
  root: HTMLElement,
  container: Node,
  offset: number
): number {
  const range = document.createRange();
  range.selectNodeContents(root);
  range.setEnd(container, offset);
  return unitLength(range.cloneContents());
}

function resolveFlatOffset(
  root: HTMLElement,
  target: number
): { node: Node; offset: number } {
  let remaining = target;

  function walk(parent: Node): { node: Node; offset: number } | null {
    const children = parent.childNodes;
    for (let i = 0; i < children.length; i++) {
      const child = children[i]!;
      if (child.nodeType === Node.TEXT_NODE) {
        const len = child.textContent?.length ?? 0;
        if (remaining <= len) return { node: child, offset: remaining };
        remaining -= len;
      } else if (isAtomicNode(child)) {
        if (remaining === 0) return { node: parent, offset: i };
        remaining -= 1;
        if (remaining === 0) return { node: parent, offset: i + 1 };
      } else {
        const found = walk(child);
        if (found) return found;
      }
    }
    return null;
  }

  return walk(root) ?? { node: root, offset: root.childNodes.length };
}

export function captureSnapshot(element: HTMLElement): EditableSnapshot {
  const end = unitLength(element);
  let selStart = end;
  let selEnd = end;
  const sel = window.getSelection();
  if (sel && sel.rangeCount > 0) {
    const range = sel.getRangeAt(0);
    if (
      element.contains(range.startContainer) &&
      element.contains(range.endContainer)
    ) {
      selStart = boundaryToFlatOffset(
        element,
        range.startContainer,
        range.startOffset
      );
      selEnd = boundaryToFlatOffset(
        element,
        range.endContainer,
        range.endOffset
      );
    }
  }
  // Strip transient tile-highlight classes so a restore can't resurrect them.
  const clone = element.cloneNode(true) as HTMLElement;
  clone
    .querySelectorAll(
      ".rich-input-tile-selected, .rich-input-tile-in-selection"
    )
    .forEach((tile) => {
      tile.classList.remove(
        "rich-input-tile-selected",
        "rich-input-tile-in-selection"
      );
    });
  return { html: clone.innerHTML, selStart, selEnd };
}

/**
 * `snapshot.html` must come from `captureSnapshot` of the same element,
 * never from external input — the innerHTML write would be an XSS sink.
 */
export function restoreSnapshot(
  element: HTMLElement,
  snapshot: EditableSnapshot
): void {
  element.innerHTML = snapshot.html;
  const sel = window.getSelection();
  if (!sel) return;
  const start = resolveFlatOffset(element, snapshot.selStart);
  const end =
    snapshot.selEnd === snapshot.selStart
      ? start
      : resolveFlatOffset(element, snapshot.selEnd);
  const range = document.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset);
  sel.removeAllRanges();
  sel.addRange(range);
}

export function snapshotsEqual(
  a: EditableSnapshot,
  b: EditableSnapshot
): boolean {
  return (
    a.html === b.html && a.selStart === b.selStart && a.selEnd === b.selEnd
  );
}

export const MAX_UNDO_ENTRIES = 100;
// Paste tiles can hold very large text; bound total retained snapshot HTML.
export const MAX_UNDO_TOTAL_CHARS = 2_000_000;

/** Append to an undo/redo stack, enforcing the entry and total-size caps. */
export function pushBoundedSnapshot(
  stack: EditableSnapshot[],
  snapshot: EditableSnapshot
): void {
  stack.push(snapshot);
  if (stack.length > MAX_UNDO_ENTRIES) stack.shift();
  let total = 0;
  for (let i = stack.length - 1; i >= 0; i--) {
    total += stack[i]!.html.length;
    if (total > MAX_UNDO_TOTAL_CHARS) {
      // Drop the entry that crossed the cap and everything older, but always
      // retain the newest entry even if it alone exceeds the cap.
      stack.splice(0, Math.min(i + 1, stack.length - 1));
      break;
    }
  }
}

// ─── Text Content Extraction ────────────────────────────────────────────────

const BLOCK_TAGS = new Set([
  "DIV",
  "P",
  "BLOCKQUOTE",
  "LI",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
]);

export function getTextContent(element: HTMLElement): string {
  const parts: string[] = [];
  const nodes = Array.from(element.childNodes);
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]!;
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push(node.textContent ?? "");
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as HTMLElement;
      if (el.hasAttribute("data-rich-tile")) {
        parts.push(el.getAttribute("data-text") ?? "");
      } else if (el.tagName === "BR") {
        parts.push("\n");
      } else {
        if (i > 0 && BLOCK_TAGS.has(el.tagName)) {
          parts.push("\n");
        }
        parts.push(getTextContent(el));
      }
    }
  }
  return parts.join("");
}

/**
 * Remove the stray leading `<br>` Chrome inserts when the last char before a
 * leading inline tile is deleted. Scoped to a `<br>` immediately followed by a
 * rich tile so a normal leading newline (followed by text) is preserved.
 * Returns whether anything was removed.
 */
export function stripLeadingBr(el: HTMLElement): boolean {
  const first = el.firstChild;
  const next = first?.nextSibling;
  if (
    first?.nodeName === "BR" &&
    next instanceof HTMLElement &&
    next.hasAttribute("data-rich-tile")
  ) {
    el.removeChild(first);
    return true;
  }
  return false;
}

// ─── Token Deletion (rich-tile insertion) ───────────────────────────────────

/**
 * Delete `token` around the collapsed cursor: `token.before` ends at the caret
 * and `token.after` starts there. Verifies that the characters to remove equal
 * it first, else bails and restores the caret. Returns whether it was removed.
 */
export function deleteTokenAtCursor(
  el: HTMLElement,
  token: CaretText
): boolean {
  if (!token.before) return false;
  const text = token.before + token.after;
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return false;
  const range = sel.getRangeAt(0);
  if (!range.collapsed || !el.contains(range.startContainer)) return false;

  const { startContainer, startOffset } = range;
  const start = startOffset - token.before.length;

  // Fast path: the token lives entirely within the caret's text node.
  if (
    startContainer.nodeType === Node.TEXT_NODE &&
    start >= 0 &&
    startContainer.textContent?.slice(start, start + text.length) === text
  ) {
    range.setStart(startContainer, start);
    range.setEnd(startContainer, start + text.length);
    range.deleteContents();
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }

  // Fallback for node-spanning tokens; modify is absent in jsdom. Steps count
  // code points, not UTF-16 units.
  if (typeof sel.modify !== "function") return false;
  for (const _ of token.after) sel.modify("move", "forward", "character");
  for (const _ of text) sel.modify("extend", "backward", "character");
  if (sel.toString() === text) {
    sel.deleteFromDocument();
    return true;
  }
  const restored = document.createRange();
  restored.setStart(startContainer, startOffset);
  restored.collapse(true);
  sel.removeAllRanges();
  sel.addRange(restored);
  return false;
}
