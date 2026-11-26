"use client";

import {
  type RefObject,
  useCallback,
  useEffect,
  useEffectEvent,
  useReducer,
  useRef,
  useState,
} from "react";
import {
  type BrowserSocketState,
  browserStreamUrl,
  createBrowserStreamClient,
  createFramePainter,
  type BrowserStreamClient,
} from "@/lib/chat/browser/stream";
import type {
  BrowserConnectionState,
  BrowserDownload,
  BrowserFileChooser,
  BrowserPointer,
  BrowserServerMessage,
  BrowserTab,
  BrowserViewerControl,
  BrowserViewerMessage,
  BrowserViewport,
} from "@/lib/chat/browser/types";

/** What the viewer knows of the chat's browser. */
interface BrowserViewState {
  connection: BrowserConnectionState;
  tabs: BrowserTab[];
  selectedTabId: string | null;
  viewport: BrowserViewport | null;
  // Who drives the selected tab; null until the service says
  control: BrowserViewerControl | null;
  fileChooser: BrowserFileChooser | null;
  // The agent's last cursor, on the tab that was selected when it came
  agentPointer: { tab: string | null; pointer: BrowserPointer } | null;
}

const INITIAL_BROWSER_VIEW: BrowserViewState = {
  connection: "connecting",
  tabs: [],
  selectedTabId: null,
  viewport: null,
  control: null,
  fileChooser: null,
  agentPointer: null,
};

type BrowserViewAction =
  | { type: "socket"; state: BrowserSocketState }
  | { type: "message"; message: BrowserServerMessage }
  | { type: "answeredFileChooser" }
  // The viewer closed its connection, to open a new one
  | { type: "reset" }
  // The viewer moved to another chat
  | { type: "clear" };

/** The view's state after a socket change or a message. */
function browserViewReducer(
  state: BrowserViewState,
  action: BrowserViewAction
): BrowserViewState {
  switch (action.type) {
    case "socket":
      switch (action.state) {
        case "connecting":
          // Retries stay "disconnected" until the service answers
          return state.connection === "disconnected"
            ? state
            : { ...state, connection: "connecting" };
        case "disconnected":
        case "disabled":
        case "unreachable":
        case "error":
          // The service releases a closed viewer's control and file chooser
          return {
            ...state,
            connection: action.state,
            control: null,
            fileChooser: null,
          };
      }
      return state;
    case "answeredFileChooser":
      return { ...state, fileChooser: null };
    case "clear":
      return INITIAL_BROWSER_VIEW;
    case "reset":
      return {
        ...state,
        connection: "connecting",
        control: null,
        fileChooser: null,
      };
    case "message": {
      const { message } = action;
      switch (message.type) {
        case "starting":
          return { ...state, connection: "starting" };
        case "tabs":
          return {
            ...state,
            connection: "live",
            tabs: message.tabs,
            selectedTabId: message.selected,
            // The service offers the newly selected tab's chooser again
            fileChooser:
              message.selected === state.selectedTabId
                ? state.fileChooser
                : null,
          };
        case "viewport":
          return {
            ...state,
            viewport: { width: message.width, height: message.height },
          };
        case "control":
          return {
            ...state,
            control: message.controller,
            fileChooser:
              message.controller === "you" ? state.fileChooser : null,
          };
        case "fileChooser":
          return {
            ...state,
            fileChooser: { id: message.id, multiple: message.multiple },
          };
        case "fileChooserClosed":
          return state.fileChooser?.id === message.id
            ? { ...state, fileChooser: null }
            : state;
        case "pointer":
          return {
            ...state,
            agentPointer: {
              tab: state.selectedTabId,
              pointer: {
                phase: message.phase,
                x: message.x,
                y: message.y,
                sequence: message.sequence,
              },
            },
          };
        case "download":
        case "error":
          return state;
      }
    }
  }
}

interface UseBrowserStreamOptions {
  sessionId: string | null;
  // Connects while true and the canvas is mounted; the api_server keeps the
  // VM awake for a viewer
  active: boolean;
  // `sessionId` is the chat whose browser downloaded the file
  onDownload: (download: BrowserDownload, sessionId: string) => void;
  onError: (message: string) => void;
}

export interface BrowserStream {
  state: BrowserViewState;
  // The canvas that the frames paint on
  canvasRef: RefObject<HTMLCanvasElement | null>;
  // Whether the canvas holds a frame of this connection
  hasFrame: boolean;
  send: (message: BrowserViewerMessage) => boolean;
  // Connects again after the connection stopped
  retry: () => void;
  // False when the answer was not sent; the prompt then stays
  answerFileChooser: (id: string, paths: string[]) => boolean;
  // The surface's drop of its queued mouse moves and wheels, which belong
  // to the page that was selected when they were queued
  dropInputRef: RefObject<(() => void) | null>;
}

/**
 * The chat's browser stream while `active`: frames painted on the canvas,
 * the chat's tabs, the control state and the page's prompts. The tabs stay
 * known after the stream stops.
 */
export function useBrowserStream({
  sessionId,
  active,
  onDownload,
  onError,
}: UseBrowserStreamOptions): BrowserStream {
  const [state, dispatch] = useReducer(
    browserViewReducer,
    INITIAL_BROWSER_VIEW
  );
  const [hasFrame, setHasFrame] = useState(false);
  // Another chat's tabs are not this chat's
  const [viewedSessionId, setViewedSessionId] = useState(sessionId);
  if (viewedSessionId !== sessionId) {
    setViewedSessionId(sessionId);
    dispatch({ type: "clear" });
  }
  const [generation, setGeneration] = useState(0);
  const clientRef = useRef<BrowserStreamClient | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dropInputRef = useRef<(() => void) | null>(null);

  const download = useEffectEvent(onDownload);
  const error = useEffectEvent(onError);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!active || sessionId === null || !canvas) return;
    const painter = createFramePainter(canvas, () => setHasFrame(true));
    // Undefined until this connection's first tab list
    let selected: string | null | undefined;
    const client = createBrowserStreamClient({
      url: browserStreamUrl(sessionId, window.location),
      events: {
        onState: (socketState) => {
          painter.clear();
          setHasFrame(false);
          dispatch({ type: "socket", state: socketState });
        },
        onFrame: (jpeg) => painter.paint(jpeg),
        onMessage: (message) => {
          if (message.type === "download") download(message, sessionId);
          else if (message.type === "error") error(message.message);
          else if (message.type === "tabs") {
            // The old page's frame stays hidden, and takes no clicks, until
            // the new page's first frame
            if (selected !== undefined && message.selected !== selected) {
              dropInputRef.current?.();
              painter.clear();
              setHasFrame(false);
            }
            selected = message.selected;
          }
          dispatch({ type: "message", message });
        },
      },
    });
    clientRef.current = client;
    return () => {
      painter.stop();
      client.stop();
      if (clientRef.current === client) clientRef.current = null;
      setHasFrame(false);
      dispatch({ type: "reset" });
    };
  }, [active, sessionId, generation]);

  const send = useCallback((message: BrowserViewerMessage) => {
    if (message.type === "selectTab") dropInputRef.current?.();
    return clientRef.current?.send(message) ?? false;
  }, []);
  const retry = useCallback(() => setGeneration((value) => value + 1), []);
  const answerFileChooser = useCallback(
    (id: string, paths: string[]) => {
      if (!send({ type: "fileChooser", id, paths })) return false;
      dispatch({ type: "answeredFileChooser" });
      return true;
    },
    [send]
  );
  return {
    state,
    canvasRef,
    hasFrame,
    send,
    retry,
    answerFileChooser,
    dropInputRef,
  };
}
