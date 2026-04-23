/**
 * Move cursor to end of a contentEditable element.
 */
export function setCursorToEnd(element: HTMLElement): void {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(element);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
}

/**
 * Insert a plain-text string at the current cursor position within a
 * contentEditable element. If the element doesn't have focus or a valid
 * selection, appends to the end. Returns the element's new text content.
 */
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

/**
 * Read the plain-text content of a contentEditable element, converting
 * <br> elements to newlines via DOM traversal (avoids innerText reflow).
 */
export function getTextContent(element: HTMLElement): string {
  const parts: string[] = [];
  const nodes = Array.from(element.childNodes);
  for (const node of nodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push(node.textContent ?? "");
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as HTMLElement;
      if (el.tagName === "BR") {
        parts.push("\n");
      } else {
        parts.push(getTextContent(el));
      }
    }
  }
  return parts.join("");
}
