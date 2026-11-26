// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).
import { findOccurrences } from "@/lib/chatFind/match";

/** Marks the searchable text of one message; its value is `chatFindTextKey`. */
const CHAT_FIND_TEXT_ATTRIBUTE = "data-chat-find-text";
/** Marks text inside a searchable scope that find skips, such as a citation chip. */
const CHAT_FIND_IGNORE_ATTRIBUTE = "data-chat-find-ignore";

const CHAT_FIND_HIGHLIGHT = "onyx-chat-find";
const CHAT_FIND_ACTIVE_HIGHLIGHT = "onyx-chat-find-active";

/**
 * A clipped block that find can unfold, with `data-chat-find-fold="closed"`
 * while clipped. Find sends it this event to unfold it.
 */
export const CHAT_FIND_UNFOLD_EVENT = "chatfindunfold";

// Rendered text that the searched message text does not hold.
const IGNORE_SELECTOR = [
  `[${CHAT_FIND_IGNORE_ATTRIBUTE}]`,
  "svg",
  ".katex",
  ".opal-code-panel-header",
  ".opal-code-panel-copy",
  '[role="toolbar"]',
  // Footnotes: the answer's searched text leaves them out.
  'a[href^="#user-content-fn-"]',
  "[data-footnotes]",
].join(", ");

// A match never spans these: the searched text splits at them too.
const BLOCK_TAGS = new Set([
  "address",
  "article",
  "aside",
  "blockquote",
  "br",
  "dd",
  "details",
  "div",
  "dl",
  "dt",
  "figcaption",
  "figure",
  "footer",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "hr",
  "li",
  "main",
  "nav",
  "ol",
  "p",
  "pre",
  "section",
  "summary",
  "table",
  "tbody",
  "td",
  "th",
  "thead",
  "tr",
  "ul",
]);

/** The ranges of `query` in each searchable scope under `root`, by scope key. */
export function collectChatFindRanges(
  root: Element,
  query: string
): Map<string, Range[]> {
  const ranges = new Map<string, Range[]>();
  if (!query) return ranges;
  const selector = `[${CHAT_FIND_TEXT_ATTRIBUTE}]`;
  for (const scope of Array.from(root.querySelectorAll(selector))) {
    if (scope.parentElement?.closest(selector)) continue;
    const key = scope.getAttribute(CHAT_FIND_TEXT_ATTRIBUTE);
    if (!key) continue;
    const scopeRanges = ranges.get(key) ?? [];
    ranges.set(key, scopeRanges);

    let text = "";
    // `map` turns a node's offset in `text` into its offset in the node:
    // a CRLF is one space in `text` but two characters in the node.
    let nodes: { node: Node; start: number; end: number; map: number[] }[] = [];
    const flush = () => {
      let startIndex = 0;
      let endIndex = 0;
      for (const offset of findOccurrences(text, query)) {
        while (
          startIndex < nodes.length &&
          (nodes[startIndex]?.end ?? 0) <= offset
        ) {
          startIndex++;
        }
        if (endIndex < startIndex) endIndex = startIndex;
        while (
          endIndex < nodes.length &&
          (nodes[endIndex]?.end ?? 0) < offset + query.length
        ) {
          endIndex++;
        }
        const start = nodes[startIndex];
        const end = nodes[endIndex];
        if (!start || !end) continue;
        const range = document.createRange();
        range.setStart(start.node, start.map[offset - start.start] ?? 0);
        range.setEnd(end.node, end.map[offset + query.length - end.start] ?? 0);
        scopeRanges.push(range);
      }
      text = "";
      nodes = [];
    };
    const visit = (node: Node) => {
      if (node instanceof Element && node.matches(IGNORE_SELECTOR)) {
        flush();
        return;
      }
      const block =
        node instanceof Element && BLOCK_TAGS.has(node.tagName.toLowerCase());
      if (block) flush();
      if (node.nodeType === Node.TEXT_NODE) {
        const raw = node.nodeValue ?? "";
        const start = text.length;
        const map: number[] = [];
        for (let i = 0; i < raw.length; i++) {
          map.push(i);
          if (raw[i] === "\r" && raw[i + 1] === "\n") i++;
          text += raw[i] === "\n" ? " " : raw[i];
        }
        map.push(raw.length);
        nodes.push({ node, start, end: text.length, map });
      }
      node.childNodes.forEach(visit);
      if (block) flush();
    };
    visit(scope);
    flush();
  }
  return ranges;
}

function highlightsSupported(): boolean {
  return (
    typeof CSS !== "undefined" &&
    "highlights" in CSS &&
    typeof Highlight !== "undefined"
  );
}

export interface ChatFindPainter {
  /** Paints every match and clears the active one. */
  paint: (ranges: Map<string, Range[]>) => void;
  /** Paints `range` as the active match. */
  select: (range: Range | null) => void;
  clear: () => void;
}

/**
 * Paints matches with the CSS Custom Highlight API, so the rendered text and
 * what the user copies stay as they are. Does nothing where it is missing.
 */
export function createChatFindPainter(): ChatFindPainter {
  if (!highlightsSupported()) {
    return { paint: () => {}, select: () => {}, clear: () => {} };
  }
  const all = new Highlight();
  const active = new Highlight();
  let selected: Range | null = null;
  CSS.highlights.set(CHAT_FIND_HIGHLIGHT, all);
  CSS.highlights.set(CHAT_FIND_ACTIVE_HIGHLIGHT, active);
  return {
    paint: (ranges) => {
      all.clear();
      active.clear();
      selected = null;
      for (const scopeRanges of ranges.values()) {
        for (const range of scopeRanges) all.add(range);
      }
    },
    select: (range) => {
      if (selected) all.add(selected);
      selected = range;
      active.clear();
      if (range) {
        all.delete(range);
        active.add(range);
      }
    },
    clear: () => {
      CSS.highlights.delete(CHAT_FIND_HIGHLIGHT);
      CSS.highlights.delete(CHAT_FIND_ACTIVE_HIGHLIGHT);
    },
  };
}

/**
 * Shows a match that a fold hides. A closed `<details>` opens at once (its
 * summary shows when closed). A clipped fold gets `CHAT_FIND_UNFOLD_EVENT`
 * when the match lies below its edge; it unfolds on its next render, so the
 * caller waits for that. Returns whether it is waiting.
 */
export function revealFoldedMatch(range: Range, container: Element): boolean {
  let waiting = false;
  for (
    let element = range.startContainer.parentElement;
    element && element !== container;
    element = element.parentElement
  ) {
    if (element instanceof HTMLDetailsElement) {
      if (
        !element.open &&
        !element
          .querySelector(":scope > summary")
          ?.contains(range.startContainer)
      ) {
        element.open = true;
      }
    } else if (
      element instanceof HTMLElement &&
      element.dataset.chatFindFold === "closed" &&
      range.getBoundingClientRect().bottom >
        element.getBoundingClientRect().bottom
    ) {
      element.dispatchEvent(new Event(CHAT_FIND_UNFOLD_EVENT));
      waiting = true;
    }
  }
  return waiting;
}

const MATCH_VIEW_MARGIN_PX = 96;

/**
 * Scrolls the least distance that shows `range` in the container, clear of
 * its edges and of the composer laid over its bottom. Returns whether it
 * scrolled.
 */
export function scrollRangeIntoView(
  container: HTMLElement,
  range: Range,
  beforeScroll: () => void
): boolean {
  for (
    let element = range.startContainer.parentElement;
    element && element !== container;
    element = element.parentElement
  ) {
    if (element.scrollWidth <= element.clientWidth) continue;
    const rect = range.getBoundingClientRect();
    const box = element.getBoundingClientRect();
    if (rect.left < box.left) element.scrollLeft += rect.left - box.left - 16;
    else if (rect.right > box.right) {
      element.scrollLeft += rect.right - box.right + 16;
    }
  }
  const rect = range.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  const view = container.getBoundingClientRect();
  const bottomInset =
    parseFloat(getComputedStyle(container).scrollPaddingBottom) || 0;
  const margin = Math.min(
    MATCH_VIEW_MARGIN_PX,
    Math.max(0, (view.height - bottomInset - rect.height) / 2)
  );
  const top = view.top + margin;
  const bottom = view.bottom - bottomInset - margin;
  const delta =
    rect.top < top
      ? rect.top - top
      : rect.bottom > bottom
        ? rect.bottom - bottom
        : 0;
  if (Math.abs(delta) < 1) return false;
  beforeScroll();
  container.scrollTop += delta;
  return true;
}

/** Scrolls a row's top near the container's top, so the row mounts. */
export function scrollRowIntoView(
  container: HTMLElement,
  row: Element,
  beforeScroll: () => void
): void {
  const delta =
    row.getBoundingClientRect().top -
    container.getBoundingClientRect().top -
    MATCH_VIEW_MARGIN_PX;
  beforeScroll();
  container.scrollTop += delta;
}
