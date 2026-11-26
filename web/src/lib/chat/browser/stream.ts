/**
 * The chat browser's stream client and the pure parts of its viewer: message
 * parsing, coordinate mapping, click counting and frame painting.
 *
 * Ported from T3 Code (packages/client-runtime/src/preview/serverBrowserStream.ts
 * and apps/web/src/browser/ServerBrowserSurface.tsx).
 * Copyright (c) 2026 T3 Tools Inc. Licensed under the MIT License.
 */
import { stripBidiControls } from "@opal/utils";
import { PacketType } from "@/app/app/services/streamingModels";
import type {
  BrowserDialog,
  BrowserMouseButton,
  BrowserPointer,
  BrowserServerMessage,
  BrowserTab,
  BrowserViewerControl,
  BrowserViewerMessage,
  BrowserViewport,
} from "@/lib/chat/browser/types";

// Close codes of the api_server's websocket route
const BROWSER_CLOSE_FORBIDDEN = 4403;
const BROWSER_CLOSE_NOT_FOUND = 4404;
const BROWSER_CLOSE_UNAVAILABLE = 4503;
// A refused handshake, such as for a signed-out user, closes with 1006 and
// no code of its own, so the client stops after this many in a row
const MAX_REFUSED_CONNECTS = 6;

// The tool whose start opens the Browser tab
const BROWSER_OPEN_TOOL_NAME = "browser_open";

/**
 * The URL that the URL bar's text opens, trimmed; null when empty. The
 * browser service adds a missing scheme.
 */
export function browserUrlFromInput(input: string): string | null {
  return input.trim() || null;
}

/**
 * A page's name for its tab, as T3 Code names a preview tab: its title, else
 * its URL's host. Null when it has neither, such as a new tab.
 */
export function browserPageTitle(
  page: Pick<BrowserTab, "title" | "url">
): string | null {
  const title = stripBidiControls(page.title).trim();
  if (title) return title;
  try {
    return new URL(page.url).host || null;
  } catch {
    return null;
  }
}

/** Whether a page shows nothing yet, as a new tab before its first URL. A
 * blank page with a title has content (a popup the opener wrote). */
export function isBlankBrowserPage(
  page: Pick<BrowserTab, "url" | "loading" | "title">
): boolean {
  return (
    !page.loading &&
    page.title.trim() === "" &&
    (page.url === "" || page.url === "about:blank")
  );
}

/** Whether a stream packet's object starts the `browser_open` tool. */
export function isBrowserOpenStart(obj: {
  type: string;
  tool_name?: unknown;
}): boolean {
  return (
    obj.type === PacketType.CUSTOM_TOOL_START &&
    obj.tool_name === BROWSER_OPEN_TOOL_NAME
  );
}

const MULTI_CLICK_MS = 500;
const MULTI_CLICK_SLOP_PX = 4;
const WHEEL_LINE_PX = 16;

/** The websocket URL of a chat's browser view, on the page's own origin. */
export function browserStreamUrl(
  sessionId: string,
  location: Pick<Location, "protocol" | "host">
): string {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/api/chat/sessions/${encodeURIComponent(
    sessionId
  )}/browser/ws`;
}

// The service's limit on one `text` message, in UTF-16 units
const BROWSER_TEXT_MAX = 10_000;

/** Text in `text` messages the service accepts, without a split surrogate pair. */
export function splitBrowserText(text: string): string[] {
  const chunks: string[] = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + BROWSER_TEXT_MAX, text.length);
    const last = text.charCodeAt(end - 1);
    if (end < text.length && last >= 0xd800 && last <= 0xdbff) end -= 1;
    chunks.push(text.slice(start, end));
    start = end;
  }
  return chunks;
}

/** The modifier bitmask: alt 1, ctrl 2, meta 4, shift 8. */
export function browserModifiers(event: {
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}): number {
  return (
    (event.altKey ? 1 : 0) |
    (event.ctrlKey ? 2 : 0) |
    (event.metaKey ? 4 : 0) |
    (event.shiftKey ? 8 : 0)
  );
}

/** The wait before reconnect attempt `failures` (0 first). */
export function reconnectDelayMs(failures: number): number {
  return Math.min(500 * 2 ** failures, 10_000);
}

// ---------------------------------------------------------------------------
// Message parsing
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isDialog(value: unknown): value is BrowserDialog | null {
  return (
    value === null ||
    (isRecord(value) &&
      typeof value.type === "string" &&
      typeof value.message === "string")
  );
}

function isBrowserPage(value: unknown): value is BrowserTab {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.url === "string" &&
    typeof value.title === "string" &&
    typeof value.loading === "boolean" &&
    isDialog(value.dialog ?? null)
  );
}

function isViewerControl(value: unknown): value is BrowserViewerControl {
  return (
    value === "agent" ||
    value === "you" ||
    value === "another-viewer" ||
    value === "none"
  );
}

/** A server text message, or `null` when it is not one the viewer knows. */
export function parseBrowserServerMessage(
  data: string
): BrowserServerMessage | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isRecord(parsed)) return null;
  const m = parsed;
  switch (m.type) {
    case "starting":
      return { type: "starting" };
    case "tabs": {
      if (!Array.isArray(m.tabs)) return null;
      const tabs = m.tabs.filter(isBrowserPage).map(
        (tab): BrowserTab => ({
          id: tab.id,
          url: tab.url,
          title: tab.title,
          loading: tab.loading,
          dialog: tab.dialog ?? null,
        })
      );
      const selected = typeof m.selected === "string" ? m.selected : null;
      return { type: "tabs", tabs, selected };
    }
    case "viewport":
      return isFiniteNumber(m.width) && isFiniteNumber(m.height)
        ? { type: "viewport", width: m.width, height: m.height }
        : null;
    case "control":
      return isViewerControl(m.controller)
        ? { type: "control", controller: m.controller }
        : null;
    case "pointer":
      return (m.phase === "move" || m.phase === "click") &&
        isFiniteNumber(m.x) &&
        isFiniteNumber(m.y) &&
        isFiniteNumber(m.sequence)
        ? {
            type: "pointer",
            phase: m.phase,
            x: m.x,
            y: m.y,
            sequence: m.sequence,
          }
        : null;
    case "fileChooser":
      return typeof m.id === "string" && typeof m.multiple === "boolean"
        ? { type: "fileChooser", id: m.id, multiple: m.multiple }
        : null;
    case "fileChooserClosed":
      return typeof m.id === "string"
        ? { type: "fileChooserClosed", id: m.id }
        : null;
    case "download":
      return typeof m.fileName === "string"
        ? { type: "download", fileName: m.fileName }
        : null;
    case "error":
      return typeof m.message === "string"
        ? { type: "error", message: m.message }
        : null;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Coordinates
// ---------------------------------------------------------------------------

interface Size {
  width: number;
  height: number;
}

interface Box extends Size {
  left: number;
  top: number;
}

/** A point on the page, in CSS px, with the page px per screen px. */
export interface PagePoint {
  x: number;
  y: number;
  scale: number;
}

/** Where the frame sits in its `object-contain` box. */
function containedFrame(box: Size, frame: Size): Box | null {
  if (!(frame.width > 0 && frame.height > 0)) return null;
  const fit = Math.min(box.width / frame.width, box.height / frame.height);
  const width = frame.width * fit;
  const height = frame.height * fit;
  if (!(width > 0 && height > 0)) return null;
  return {
    left: (box.width - width) / 2,
    top: (box.height - height) / 2,
    width,
    height,
  };
}

/**
 * Maps a client point over the canvas to the page. `rect` is the canvas's
 * client rect, `frame` its bitmap size. Outside the frame it gives `null`,
 * or, with `clamp`, the nearest edge point (for drags that leave it).
 */
export function pagePointFromClient(
  clientX: number,
  clientY: number,
  rect: Box,
  frame: Size,
  viewport: BrowserViewport,
  clamp: boolean
): PagePoint | null {
  const shown = containedFrame(rect, frame);
  if (!shown) return null;
  const scale = viewport.width / shown.width;
  const x = (clientX - rect.left - shown.left) * scale;
  const y = (clientY - rect.top - shown.top) * (viewport.height / shown.height);
  const inside =
    x >= 0 && y >= 0 && x <= viewport.width && y <= viewport.height;
  if (!inside && !clamp) return null;
  return {
    x: Math.min(Math.max(x, 0), viewport.width),
    y: Math.min(Math.max(y, 0), viewport.height),
    scale,
  };
}

/** Where the agent cursor goes in the canvas's box, in CSS px from its corner. */
export function agentCursorPosition(
  pointer: Pick<BrowserPointer, "x" | "y">,
  box: Size,
  frame: Size,
  viewport: BrowserViewport
): { left: number; top: number } | null {
  const shown = containedFrame(box, frame);
  if (!shown || !(viewport.width > 0 && viewport.height > 0)) return null;
  return {
    left: shown.left + (pointer.x * shown.width) / viewport.width,
    top: shown.top + (pointer.y * shown.height) / viewport.height,
  };
}

/** A wheel delta's px per unit: lines are 16px, pages the viewport. */
export function wheelDeltaUnit(
  deltaMode: number,
  viewportHeight: number
): number {
  // WheelEvent.DOM_DELTA_LINE and DOM_DELTA_PAGE
  if (deltaMode === 1) return WHEEL_LINE_PX;
  if (deltaMode === 2) return viewportHeight;
  return 1;
}

export interface LastClick {
  button: BrowserMouseButton;
  time: number;
  x: number;
  y: number;
  count: number;
}

/** The click count of a press: one more than the last near and quick one. */
export function nextClick(
  last: LastClick | null,
  button: BrowserMouseButton,
  time: number,
  x: number,
  y: number
): LastClick {
  const count =
    last &&
    last.button === button &&
    time - last.time < MULTI_CLICK_MS &&
    Math.hypot(x - last.x, y - last.y) < MULTI_CLICK_SLOP_PX
      ? last.count + 1
      : 1;
  return { button, time, x, y, count };
}

export function mouseButtonOf(button: number): BrowserMouseButton {
  return button === 0
    ? "left"
    : button === 1
      ? "middle"
      : button === 2
        ? "right"
        : "none";
}

export function pressedButtonOf(buttons: number): BrowserMouseButton {
  return buttons & 1
    ? "left"
    : buttons & 2
      ? "right"
      : buttons & 4
        ? "middle"
        : "none";
}

/** Mouse thumb buttons: 3 is Back, 4 is Forward. */
export function historyDeltaOf(button: number): -1 | 1 | null {
  return button === 3 ? -1 : button === 4 ? 1 : null;
}

// ---------------------------------------------------------------------------
// Stream client
// ---------------------------------------------------------------------------

/** The socket's state; the viewer adds `starting` and `live` from messages. */
export type BrowserSocketState =
  | "connecting"
  | "disconnected"
  | "disabled"
  | "unreachable"
  | "error";

interface BrowserStreamEvents {
  onState: (state: BrowserSocketState) => void;
  onMessage: (message: BrowserServerMessage) => void;
  onFrame: (jpeg: ArrayBuffer) => void;
}

export interface BrowserStreamClient {
  // Sends a message; false when the socket is not open
  send: (message: BrowserViewerMessage) => boolean;
  stop: () => void;
}

interface BrowserStreamOptions {
  url: string;
  events: BrowserStreamEvents;
  createSocket?: (url: string) => WebSocket;
}

const ACK_MESSAGE = JSON.stringify({ type: "ack" });
// WebSocket.OPEN
const SOCKET_OPEN = 1;

/**
 * Opens the chat's browser stream and keeps it open: it acks each frame on
 * receipt, and reconnects after a drop with a growing wait. A forbidden,
 * unknown or unavailable chat stops it, and so do connects that never open.
 */
export function createBrowserStreamClient({
  url,
  events,
  createSocket = (target) => new WebSocket(target),
}: BrowserStreamOptions): BrowserStreamClient {
  let stopped = false;
  let socket: WebSocket | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let failures = 0;
  let refusals = 0;

  // A connect that did not open; true when the connects stop
  const refused = () => {
    if (++refusals < MAX_REFUSED_CONNECTS) return false;
    stopped = true;
    events.onState("unreachable");
    return true;
  };

  const connect = () => {
    retryTimer = null;
    if (stopped) return;
    events.onState("connecting");
    let ws: WebSocket;
    try {
      ws = createSocket(url);
    } catch {
      if (refused()) return;
      retryTimer = setTimeout(connect, reconnectDelayMs(failures++));
      events.onState("disconnected");
      return;
    }
    ws.binaryType = "arraybuffer";
    socket = ws;
    let opened = false;
    ws.addEventListener("open", () => {
      opened = true;
      refusals = 0;
    });
    ws.addEventListener("message", (event: MessageEvent<unknown>) => {
      if (socket !== ws) return;
      if (event.data instanceof ArrayBuffer) {
        ws.send(ACK_MESSAGE);
        events.onFrame(event.data);
        return;
      }
      if (typeof event.data !== "string") return;
      const message = parseBrowserServerMessage(event.data);
      if (!message) return;
      if (message.type === "tabs") failures = 0;
      events.onMessage(message);
    });
    ws.addEventListener("close", (event: CloseEvent) => {
      if (socket !== ws) return;
      socket = null;
      if (stopped) return;
      if (event.code === BROWSER_CLOSE_FORBIDDEN) {
        stopped = true;
        events.onState("disabled");
        return;
      }
      if (
        event.code === BROWSER_CLOSE_NOT_FOUND ||
        event.code === BROWSER_CLOSE_UNAVAILABLE
      ) {
        stopped = true;
        events.onState("error");
        return;
      }
      if (!opened && refused()) return;
      events.onState("disconnected");
      retryTimer = setTimeout(connect, reconnectDelayMs(failures++));
    });
    ws.addEventListener("error", () => ws.close());
  };

  connect();

  return {
    send: (message) => {
      if (socket?.readyState !== SOCKET_OPEN) return false;
      socket.send(JSON.stringify(message));
      return true;
    },
    stop: () => {
      stopped = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      const ws = socket;
      socket = null;
      ws?.close();
    },
  };
}

// ---------------------------------------------------------------------------
// Frame painter
// ---------------------------------------------------------------------------

interface BrowserFramePainter {
  paint: (jpeg: ArrayBuffer) => void;
  // Blanks the canvas and drops the frames still on their way to it
  clear: () => void;
  stop: () => void;
}

/** One decode at a time, keeping only the newest waiting frame. */
export function createFramePainter(
  canvas: HTMLCanvasElement,
  onPainted?: () => void
): BrowserFramePainter {
  const context = canvas.getContext("2d");
  let stopped = false;
  let decoding = false;
  let waiting: ArrayBuffer | null = null;
  let generation = 0;
  const draw = (jpeg: ArrayBuffer) => {
    decoding = true;
    const drawGeneration = generation;
    void createImageBitmap(new Blob([jpeg], { type: "image/jpeg" }))
      .then((bitmap) => {
        if (stopped || !context || drawGeneration !== generation) {
          bitmap.close();
          return;
        }
        if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
          canvas.width = bitmap.width;
          canvas.height = bitmap.height;
        }
        context.drawImage(bitmap, 0, 0);
        bitmap.close();
        onPainted?.();
      })
      .catch(() => undefined)
      .finally(() => {
        decoding = false;
        const next = waiting;
        waiting = null;
        if (next && !stopped) draw(next);
      });
  };
  return {
    paint: (jpeg) => {
      if (stopped) return;
      if (decoding) waiting = jpeg;
      else draw(jpeg);
    },
    clear: () => {
      generation += 1;
      waiting = null;
      context?.clearRect(0, 0, canvas.width, canvas.height);
    },
    stop: () => {
      stopped = true;
      waiting = null;
    },
  };
}
