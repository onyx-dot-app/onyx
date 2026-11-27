/**
 * The chat browser's viewer protocol. The browser service in the chat's VM
 * (deployment/craft-runtime/browser-service/src/service.ts) defines it, and
 * the api_server relays it between the chat's websocket and that service.
 */

export interface BrowserDialog {
  // "alert", "confirm", "prompt" or "beforeunload"
  type: string;
  message: string;
  // The asking frame's origin, such as "https://example.com"; null when
  // unknown or opaque
  origin: string | null;
}

/** One of the chat's browser tabs. */
export interface BrowserTab {
  id: string;
  url: string;
  title: string;
  loading: boolean;
  dialog: BrowserDialog | null;
}

/** Who drives the selected tab, from this viewer's side. */
export type BrowserViewerControl = "agent" | "you" | "another-viewer" | "none";

/** The CSS size of the selected tab's page. */
export interface BrowserViewport {
  width: number;
  height: number;
}

/** The agent's cursor, in CSS px of the page. */
export interface BrowserPointer {
  phase: "move" | "click";
  x: number;
  y: number;
  sequence: number;
}

/** The page asks for files; only the controlling viewer gets it. */
export interface BrowserFileChooser {
  id: string;
  multiple: boolean;
  // The asking frame's origin; null when unknown or opaque
  origin: string | null;
}

/** A download the service saved to the sandbox's downloads/ dir. */
export interface BrowserDownload {
  fileName: string;
}

/** A JSON message from the service (the api_server adds `starting`). */
export type BrowserServerMessage =
  | { type: "starting" }
  | { type: "tabs"; tabs: BrowserTab[]; selected: string | null }
  | ({ type: "viewport" } & BrowserViewport)
  | { type: "control"; controller: BrowserViewerControl }
  | ({ type: "pointer" } & BrowserPointer)
  | ({ type: "fileChooser" } & BrowserFileChooser)
  | { type: "fileChooserClosed"; id: string }
  | ({ type: "download" } & BrowserDownload)
  | { type: "error"; message: string };

export type BrowserMouseButton = "none" | "left" | "middle" | "right";

/** A JSON message from the viewer to the service. */
export type BrowserViewerMessage =
  | { type: "ack" }
  | { type: "selectTab"; tab: string }
  | { type: "newTab"; url?: string }
  | { type: "closeTab"; tab: string }
  | { type: "takeControl" }
  | { type: "releaseControl" }
  | {
      type: "mouse";
      action: "move" | "down" | "up";
      x: number;
      y: number;
      button: BrowserMouseButton;
      buttons: number;
      clickCount: number;
      modifiers: number;
    }
  | {
      type: "wheel";
      x: number;
      y: number;
      deltaX: number;
      deltaY: number;
      modifiers: number;
    }
  | {
      type: "key";
      action: "down" | "up";
      key: string;
      code: string;
      keyCode?: number;
      text?: string;
      modifiers: number;
    }
  | { type: "text"; text: string }
  | { type: "navigate"; url: string }
  | { type: "history"; delta: -1 | 1 }
  | { type: "reload" }
  | { type: "dialog"; accept: boolean; promptText?: string }
  | { type: "fileChooser"; id: string; paths: string[] };

/**
 * The connection's state, as the viewer shows it:
 * - connecting: the websocket opens
 * - starting: the api_server boots the chat's VM
 * - live: the service streams the chat's tabs
 * - disconnected: the connection closed; it tries again
 * - disabled: an admin turned the browser off, or the user may not view it
 * - unreachable: the websocket did not open after several connects; a retry
 *   is manual
 * - error: the chat or its sandbox is unavailable; a retry is manual
 */
export type BrowserConnectionState =
  | "connecting"
  | "starting"
  | "live"
  | "disconnected"
  | "disabled"
  | "unreachable"
  | "error";

/** The user's Chrome, as one chat sees it (the Onyx extension). */
export interface ChromeBrowserState {
  // The user's Chrome installations that are connected now
  installations: { installation_id: string }[];
  // A share request that waits in Chrome, or that the user denied
  request: "pending" | "denied" | null;
  grant: {
    tabs: { id: string; title: string; url: string }[];
    origins: string[];
    // Seconds since the epoch
    expires_at: number;
  } | null;
}
