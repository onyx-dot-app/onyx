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
import useSWR, { type SWRResponse } from "swr";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import { SvgDownload } from "@opal/icons";
import { stripBidiControls } from "@opal/utils";
import { browserDownloadUrl } from "@/lib/chat/browser/api";
import {
  RIGHT_PANEL_BROWSER_TAB,
  type ChatRightPanelAction,
  type ChatRightPanelState,
} from "@/lib/chat/rightPanel";
import { downloadFile } from "@/lib/download";
import { errorHandlingFetcher, type FetchError } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  browserPageTitle,
  type BrowserSocketState,
  browserStreamUrl,
  createBrowserStreamClient,
  createFramePainter,
  type BrowserStreamClient,
} from "@/lib/chat/browser/stream";
import type {
  BrowserConnectionState,
  ChromeBrowserState,
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
  | { type: "answeredFileChooser"; id: string }
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
      return state.fileChooser?.id === action.id
        ? { ...state, fileChooser: null }
        : state;
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
            fileChooser: {
              id: message.id,
              multiple: message.multiple,
              origin: message.origin,
            },
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
  const clientRef = useRef<{
    sessionId: string;
    client: BrowserStreamClient;
  } | null>(null);
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
    const connection = { sessionId, client };
    clientRef.current = connection;
    return () => {
      painter.stop();
      client.stop();
      if (clientRef.current === connection) clientRef.current = null;
      setHasFrame(false);
      dispatch({ type: "reset" });
    };
  }, [active, sessionId, generation]);

  // Another chat's connection, before its effect stops it, takes nothing
  const send = useCallback(
    (message: BrowserViewerMessage) => {
      const connection = clientRef.current;
      if (connection === null || connection.sessionId !== sessionId)
        return false;
      if (message.type === "selectTab") dropInputRef.current?.();
      return connection.client.send(message);
    },
    [sessionId]
  );
  const retry = useCallback(() => setGeneration((value) => value + 1), []);
  const answerFileChooser = useCallback(
    (id: string, paths: string[]) => {
      if (!send({ type: "fileChooser", id, paths })) return false;
      dispatch({ type: "answeredFileChooser", id });
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

// A browser page's tab in the panel; the browser selects the shown page
function browserPageTab(pageId: string): string {
  return `${RIGHT_PANEL_BROWSER_TAB}:${pageId}`;
}

interface UseChatBrowserTabsOptions {
  // The chat whose panel this is
  sessionId: string | null;
  // The panel is open
  open: boolean;
  state: ChatRightPanelState;
  dispatch: (action: ChatRightPanelAction) => void;
  // Called before the hook changes the panel's tab itself
  onInsideChange: () => void;
}

export interface ChatBrowserTab {
  id: string;
  // The page's title or host. Null for a page with neither, and for the tab
  // that stands for the browser until the stream lists its pages.
  title: string | null;
}

export interface ChatBrowserTabs {
  stream: BrowserStream;
  // The chat whose browser is open in the panel
  sessionId: string | null;
  // The browser is the panel's active tab
  shown: boolean;
  // The tab of the page that the browser shows
  tabId: string;
  tabs: ChatBrowserTab[];
  // False when `tabId` is not a page of the browser
  selectTab: (tabId: string) => boolean;
  // False when the tab is not the browser's, for the panel to close itself
  closeTab: (tabId: string) => boolean;
  // As T3 Code's "+" menu: each opening adds a new page and shows it
  openPage: () => void;
}

/**
 * The chat's browser in the right panel: its stream while the panel is open
 * on a chat whose browser is open, a tab per page of the browser, and the
 * toasts for its downloads and errors.
 */
export function useChatBrowserTabs({
  sessionId,
  open,
  state,
  dispatch,
  onInsideChange,
}: UseChatBrowserTabsOptions): ChatBrowserTabs {
  const tb = useTranslations("chat.browser");
  const browserSessionId = state.browserOpen ? sessionId : null;
  const browserOpen = browserSessionId !== null;
  const onDownload = useCallback(
    ({ fileName }: BrowserDownload, downloadSessionId: string) => {
      // The page names the file, so bidi controls must not disguise it
      const shownName = stripBidiControls(fileName);
      toast.info(tb("download.saved", { fileName: shownName }), {
        action: {
          icon: SvgDownload,
          label: tb("download.action"),
          // An attachment link starts the download without leaving the page
          onClick: () =>
            downloadFile(shownName, {
              url: browserDownloadUrl(downloadSessionId, fileName),
            }),
        },
      });
    },
    [tb]
  );
  const stream = useBrowserStream({
    sessionId: browserSessionId,
    active: open,
    onDownload,
    onError: (message) => toast.error(tb("error"), { description: message }),
  });
  const pages = stream.state.tabs;
  const browserLive = stream.state.connection === "live";
  // The browser selects the page that it shows: its tab is the active one
  // while the browser shows. Until the stream lists the pages, one tab
  // stands for the browser.
  const selectedPage = pages.find(
    (page) => page.id === stream.state.selectedTabId
  );
  const tabId =
    selectedPage === undefined
      ? RIGHT_PANEL_BROWSER_TAB
      : browserPageTab(selectedPage.id);
  const tabs: ChatBrowserTab[] = [
    ...pages.map(
      (page): ChatBrowserTab => ({
        id: browserPageTab(page.id),
        title: browserPageTitle(page),
      })
    ),
    ...(browserOpen && selectedPage === undefined
      ? [{ id: RIGHT_PANEL_BROWSER_TAB, title: null }]
      : []),
  ];

  const { send } = stream;
  const pageOfTab = (id: string) =>
    pages.find((page) => browserPageTab(page.id) === id);
  const selectTab = (id: string) => {
    const page = pageOfTab(id);
    if (page === undefined) return false;
    if (page.id !== selectedPage?.id) send({ type: "selectTab", tab: page.id });
    dispatch({ type: "showTab", tabId: RIGHT_PANEL_BROWSER_TAB });
    return true;
  };
  // "Open browser" before the stream is live opens its page once it is. A
  // live browser whose last page closes closes in the panel.
  // The pages asked for, and the chat whose browser gets them; closing the
  // browser drops them
  const newTabPendingRef = useRef<{ sessionId: string; count: number } | null>(
    null
  );
  const hadPagesRef = useRef(false);
  const pageCount = pages.length;
  const insideChange = useEffectEvent(onInsideChange);
  useEffect(() => {
    if (!browserLive) {
      hadPagesRef.current = false;
      return;
    }
    const pending = newTabPendingRef.current;
    newTabPendingRef.current = null;
    if (pending !== null && pending.sessionId === browserSessionId) {
      // A socket that closed since the render keeps the rest for the next
      // live render
      let count = pending.count;
      while (count > 0 && send({ type: "newTab" })) count--;
      if (count > 0) newTabPendingRef.current = { ...pending, count };
    }
    const hadPages = hadPagesRef.current;
    hadPagesRef.current = pageCount > 0;
    if (hadPages && pageCount === 0) {
      insideChange();
      dispatch({ type: "closeTab", tabId: RIGHT_PANEL_BROWSER_TAB });
    }
  }, [browserLive, browserSessionId, pageCount, send, dispatch]);
  const openPage = () => {
    if (sessionId !== null && !(browserLive && send({ type: "newTab" }))) {
      const pending = newTabPendingRef.current;
      newTabPendingRef.current = {
        sessionId,
        count: pending?.sessionId === sessionId ? pending.count + 1 : 1,
      };
    }
    dispatch({ type: "openBrowser" });
  };
  const closeTab = (id: string) => {
    // The browser closes the page; its tab goes when the page list drops it.
    // Without a connection, the panel closes the browser and its pages.
    const page = pageOfTab(id);
    if (page === undefined && id !== RIGHT_PANEL_BROWSER_TAB) return false;
    if (page !== undefined && send({ type: "closeTab", tab: page.id }))
      return true;
    newTabPendingRef.current = null;
    dispatch({ type: "closeTab", tabId: RIGHT_PANEL_BROWSER_TAB });
    return true;
  };

  return {
    stream,
    sessionId: browserSessionId,
    shown: browserOpen && state.activeId === RIGHT_PANEL_BROWSER_TAB,
    tabId,
    tabs,
    selectTab,
    closeTab,
    openPage,
  };
}

// The chat's Chrome state changes in Chrome (an approval, a stop), so the
// panel polls it while it shows, and the chat reads it once otherwise
const CHROME_POLL_MS = 2_000;

/**
 * The chat's use of the user's own Chrome; no fetch for a null chat. It
 * polls while `polling` and while the chat shares tabs, so a share that
 * ends anywhere leaves the panel soon.
 */
export function useChromeBrowserState(
  sessionId: string | null,
  polling: boolean
): SWRResponse<ChromeBrowserState, FetchError> {
  return useSWR<ChromeBrowserState, FetchError>(
    sessionId === null ? null : SWR_KEYS.chatChromeBrowser(sessionId),
    errorHandlingFetcher,
    {
      refreshInterval: (data) => (polling || data?.grant ? CHROME_POLL_MS : 0),
      shouldRetryOnError: false,
    }
  );
}
