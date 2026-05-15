export const PASTE_TILE_THRESHOLD_CHARS = 200;
export const PASTE_TILE_THRESHOLD_LINES = 3;

export function shouldCreatePasteTile(text: string): boolean {
  return (
    text.length > PASTE_TILE_THRESHOLD_CHARS ||
    text.split("\n").length > PASTE_TILE_THRESHOLD_LINES
  );
}

export function getPasteTilePreview(text: string, maxLength = 18): string {
  const firstLine = text.split("\n")[0]?.trim() ?? "";
  if (firstLine.length > maxLength) {
    return firstLine.slice(0, maxLength) + "…";
  }
  return firstLine;
}

export function getPasteTileMeta(text: string): string {
  const lines = text.split("\n");
  if (lines.length > 1) {
    return `${lines.length} lines`;
  }
  return `${text.length} chars`;
}

// Path data mirrored from @opal/icons — keep in sync with:
//   clipboard.tsx (SvgClipboard, viewBox 0 0 16 16)
//   x.tsx (SvgX, viewBox 0 0 28 28)
// We can't import the React icon components here because paste tiles are
// created as raw DOM nodes inside a contentEditable div (React doesn't
// manage the div's children), so we build the SVGs imperatively.
const CLIPBOARD_PATH =
  "M10.6667 2.66665H12C12.3536 2.66665 12.6927 2.80712 12.9428 3.05717C13.1928 3.30722 13.3333 3.64636 13.3333 3.99998V13.3333C13.3333 13.6869 13.1928 14.0261 12.9428 14.2761C12.6927 14.5262 12.3536 14.6666 12 14.6666H3.99999C3.64637 14.6666 3.30723 14.5262 3.05718 14.2761C2.80713 14.0261 2.66666 13.6869 2.66666 13.3333V3.99998C2.66666 3.64636 2.80713 3.30722 3.05718 3.05717C3.30723 2.80712 3.64637 2.66665 3.99999 2.66665H5.33332M10.6667 2.66665V1.99998C10.6667 1.63179 10.3682 1.33331 9.99999 1.33331H5.99999C5.6318 1.33331 5.33332 1.63179 5.33332 1.99998V2.66665M10.6667 2.66665V3.33331C10.6667 3.7015 10.3682 3.99998 9.99999 3.99998H5.99999C5.6318 3.99998 5.33332 3.7015 5.33332 3.33331V2.66665";

const X_PATH = "M21 7L7 21M7 7L21 21";

function createSvgIcon(
  path: string,
  viewBox: string,
  size: number,
  strokeWidth: number
): SVGSVGElement {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("viewBox", viewBox);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", String(strokeWidth));
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  const pathEl = document.createElementNS(ns, "path");
  pathEl.setAttribute("d", path);
  svg.appendChild(pathEl);
  return svg;
}

export interface RichTileConfig {
  type: string;
  text: string;
  preview: string;
  meta: string;
}

export function createRichInputTileNode(
  config: RichTileConfig
): HTMLSpanElement {
  const tile = document.createElement("span");
  tile.contentEditable = "false";
  tile.setAttribute("data-rich-tile", "");
  tile.setAttribute("data-tile-type", config.type);
  tile.setAttribute("data-text", config.text);
  tile.className = "rich-input-tile";
  tile.title =
    config.text.length > 200 ? config.text.slice(0, 200) + "…" : config.text;
  tile.setAttribute(
    "aria-label",
    "Pasted text: " + config.preview + ", " + config.meta
  );

  const icon = createSvgIcon(CLIPBOARD_PATH, "0 0 16 16", 14, 1.5);
  icon.classList.add("rich-input-tile-icon");
  tile.appendChild(icon);

  const previewSpan = document.createElement("span");
  previewSpan.className = "rich-input-tile-preview";
  previewSpan.textContent = config.preview;
  tile.appendChild(previewSpan);

  const metaSpan = document.createElement("span");
  metaSpan.className = "rich-input-tile-meta";
  metaSpan.textContent = config.meta;
  tile.appendChild(metaSpan);

  const removeBtn = document.createElement("span");
  removeBtn.className = "rich-input-tile-remove";
  removeBtn.setAttribute("data-rich-tile-remove", "");
  removeBtn.setAttribute("role", "button");
  removeBtn.setAttribute("aria-label", "Remove pasted text");
  removeBtn.appendChild(createSvgIcon(X_PATH, "0 0 28 28", 10, 2.5));
  tile.appendChild(removeBtn);

  return tile;
}

export function getAdjacentRichTile(
  range: Range,
  direction: "before" | "after"
): HTMLElement | null {
  const { startContainer, startOffset } = range;

  let candidate: Node | null = null;

  if (direction === "before") {
    if (startContainer.nodeType === Node.TEXT_NODE && startOffset === 0) {
      candidate = startContainer.previousSibling;
    } else if (
      startContainer.nodeType === Node.ELEMENT_NODE &&
      startOffset > 0
    ) {
      candidate = startContainer.childNodes[startOffset - 1] ?? null;
    }
  } else {
    if (
      startContainer.nodeType === Node.TEXT_NODE &&
      startOffset === (startContainer.textContent?.length ?? 0)
    ) {
      candidate = startContainer.nextSibling;
    } else if (startContainer.nodeType === Node.ELEMENT_NODE) {
      candidate = startContainer.childNodes[startOffset] ?? null;
    }
  }

  if (
    candidate?.nodeType === Node.ELEMENT_NODE &&
    (candidate as HTMLElement).hasAttribute("data-rich-tile")
  ) {
    return candidate as HTMLElement;
  }

  return null;
}
