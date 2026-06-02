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
 * Delete `token` immediately before the collapsed cursor, but only after
 * verifying the characters to remove equal it (else bail + restore the caret).
 * Returns whether the token was removed.
 */
export function deleteTokenBeforeCursor(
  el: HTMLElement,
  token: string
): boolean {
  const n = token.length;
  if (n <= 0) return false;
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return false;
  const range = sel.getRangeAt(0);
  if (!range.collapsed || !el.contains(range.startContainer)) return false;

  const { startContainer, startOffset } = range;

  // Fast path: the token lives entirely within the caret's text node.
  if (
    startContainer.nodeType === Node.TEXT_NODE &&
    startOffset >= n &&
    startContainer.textContent?.slice(startOffset - n, startOffset) === token
  ) {
    range.setStart(startContainer, startOffset - n);
    range.deleteContents();
    sel.removeAllRanges();
    sel.addRange(range);
    return true;
  }

  // Fallback for node-spanning tokens; modify is absent in jsdom.
  if (typeof sel.modify !== "function") return false;
  const steps = Array.from(token).length; // code points, not UTF-16 units
  for (let i = 0; i < steps; i++) sel.modify("extend", "backward", "character");
  if (sel.toString() === token) {
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
