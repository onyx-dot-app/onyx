// Tab ownership, agent calls and viewer streams. Viewer streaming, input dispatch, agent cursor,
// dialogs, file chooser and downloads are ported from T3 Code
// apps/server/src/preview/ServerBrowser.ts and ServerBrowserStream.ts (MIT, see LICENSE-T3).

import * as NodeCrypto from "node:crypto";
import * as NodeFS from "node:fs";
import * as NodeFSP from "node:fs/promises";
import * as NodeOS from "node:os";
import * as NodePath from "node:path";
import type { Socket } from "node:net";
import type {
  BrowserContext,
  CDPSession,
  Dialog,
  FileChooser,
  Page,
} from "playwright-core";
import { HUMAN_CONTROL_MESSAGE, isTimeout, OperationError, toOperationError } from "./errors.ts";
import { encodeFrame, encodeJson, KIND_JPEG, KIND_JSON, MAX_FRAME_LENGTH, readMessages } from "./framing.ts";
import type { Message } from "./framing.ts";
import * as BrowserPage from "./page.ts";
import type { Point, Target } from "./page.ts";
import { CHAT_ID_PATTERN, chatDir, normalizeUrl, reserveUniqueFile, resolveInChat } from "./paths.ts";
import { BrowserControlInterrupted, SessionControl } from "./SessionControl.ts";

const noop = () => {};

const VIEWPORT = { width: 1280, height: 800 } as const;
const VIEWER_NAVIGATION_OPTIONS = { waitUntil: "commit", timeout: BrowserPage.DEFAULT_TIMEOUT_MS } as const;
const MAX_TIMEOUT_MS = 60_000;
const CALL_GRACE_MS = 5_000;
const HELLO_TIMEOUT_MS = 10_000;
const CHAT_TAB_LIMIT = 8;
const TITLE_LIMIT = BrowserPage.TITLE_LIMIT;
// T3 ServerBrowser.ts titleChange: resolves when document.title differs from
// the reported one, watching only the title, head and root nodes.
const titleChange = (reported: string) => `new Promise((resolve) => {
  const changed = () => document.title.slice(0, ${TITLE_LIMIT}) !== ${JSON.stringify(reported)};
  if (changed()) return resolve();
  let head;
  let root;
  let title;
  const observer = new MutationObserver(() => {
    if (changed()) {
      observer.disconnect();
      resolve();
    } else if (head !== document.head || root !== document.documentElement || title !== document.querySelector('title')) {
      observe();
    }
  });
  const observe = () => {
    observer.disconnect();
    observer.observe(document, { childList: true });
    root = document.documentElement;
    head = document.head;
    title = document.querySelector('title');
    if (root) observer.observe(root, { childList: true });
    if (head) observer.observe(head, { subtree: true, childList: true, characterData: true });
    if (title && !head?.contains(title)) {
      observer.observe(title, { subtree: true, childList: true, characterData: true });
      for (let ancestor = title.parentElement; ancestor; ancestor = ancestor.parentElement) {
        observer.observe(ancestor, { childList: true });
      }
    }
  };
  observe();
})`;
const STATUS_READ_MS = 250;
// Chromium allows three unacked frames, so 100 ms pacing caps viewers near 30 fps.
const SCREENCAST_ACK_PACE_MS = 100;
const SCREENCAST_SETTLE_MS = 200;
const MAX_SOCKET_BUFFER_BYTES = 8 * 1024 * 1024;
const AGENT_CURSOR_MOVE_MS = 160;
const AGENT_CURSOR_CLICK_LEAD_MS = 40;
// A page can start downloads without a gesture, so each chat has a budget. Downloads are saved
// with the chat session (archive limit 1 GiB), and a failed save keeps the VM from idle stop.
// The budget counts saved bytes and the bytes of all downloads that still run.
const DOWNLOAD_MAX_BYTES = 256 * 1024 * 1024;
const CHAT_DOWNLOAD_LIMIT = 20;
const VIEWER_QUALITY = 70;
const MAX_TAB_URL_CHARS = 2048;
const MAX_DIALOG_MESSAGE_CHARS = 4000;
// The web chat panel sends pasted text in chunks of this size.
const MAX_INSERT_TEXT_CHARS = 10_000;
const MAX_ECHO_CHARS = 40;

export type Log = (event: string, fields?: Record<string, unknown>) => void;

type MouseButton = "left" | "middle" | "right";

type HistoryStep = "back" | "forward" | "reload";

type Frame = { readonly data: Buffer; readonly ack: () => void };

type Cast = {
  readonly session: CDPSession;
  readonly tab: Tab;
  framesInFlight: number;
  mayHaveDropped: boolean;
  settleTimer: ReturnType<typeof setTimeout> | null;
  params: Promise<void>;
  started: boolean;
  stopped: boolean;
};

type Viewer = {
  readonly id: string;
  readonly chat: ChatState;
  readonly socket: Socket;
  selected: Tab | null;
  cast: Cast | null;
  selecting: Promise<void>;
  inFlight: Frame | null;
  pending: Frame | null;
  readonly pressedKeys: Map<string, { readonly key: string; readonly code: string }>;
  readonly pressedButtons: Map<MouseButton, Point>;
  closed: boolean;
};

type OpenChooser = {
  readonly id: string;
  readonly chooser: FileChooser;
  readonly origin: string | null;
  readonly offeredTo: string | null;
};

type Tab = {
  readonly id: string;
  readonly chat: ChatState;
  readonly page: Page;
  readonly cdp: CDPSession;
  readonly control: SessionControl;
  readonly viewers: Set<Viewer>;
  dialog: Dialog | null;
  dialogOrigin: string | null;
  dialogOpened: PromiseWithResolvers<void>;
  fileChooser: OpenChooser | null;
  loading: boolean;
  title: string;
  titleWatch: { readonly contextId: number; readonly title: string } | null;
  agentUsed: boolean;
  closing: boolean;
  captureLock: Promise<void>;
  capturing: number;
  readonly frames: Set<string>;
};

type ChatState = {
  readonly id: string;
  readonly tabs: Map<string, Tab>;
  current: string | null;
  readonly viewers: Set<Viewer>;
  tabsScheduled: boolean;
  opening: number;
  downloads: number;
  downloadBytes: number;
};

type DownloadStart = { readonly guid: string; readonly frameId: string; readonly suggestedFilename: string };
type DownloadProgress = {
  readonly guid: string;
  readonly state: "inProgress" | "completed" | "canceled";
  readonly receivedBytes: number;
};
type ActiveDownload = { readonly chat: ChatState; readonly fileName: string; receivedBytes: number };

type ViewerControl = "none" | "you" | "another-viewer" | "agent";

// Mirrors BrowserServerMessage in the web chat panel.
type ViewerEvent =
  | { readonly type: "tabs"; readonly tabs: Array<TabJson>; readonly selected: string | null }
  | { readonly type: "viewport"; readonly width: number; readonly height: number }
  | { readonly type: "control"; readonly controller: ViewerControl }
  | {
      readonly type: "pointer";
      readonly phase: "move" | "click";
      readonly x: number;
      readonly y: number;
      readonly sequence: number;
    }
  | { readonly type: "fileChooser"; readonly id: string; readonly multiple: boolean; readonly origin: string | null }
  | { readonly type: "fileChooserClosed"; readonly id: string }
  | { readonly type: "download"; readonly fileName: string }
  | { readonly type: "error"; readonly message: string };

export type TabJson = {
  readonly id: string;
  readonly url: string;
  readonly title: string;
  readonly loading: boolean;
  readonly controller: "agent" | "human" | "none";
  readonly dialog: { readonly type: string; readonly message: string; readonly origin: string | null } | null;
};

/** The frame's origin, or null for an opaque origin such as about:blank or data:. */
const originOf = (url: string) => {
  try {
    const origin = new URL(url).origin;
    return origin === "null" ? null : origin;
  } catch {
    return null;
  }
};

const sleepUntil = (deadline: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, Math.max(0, deadline - Date.now())));

const asRecord = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const num = (value: unknown, fallback = 0) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

const modifiersOf = (message: Record<string, unknown>) => {
  const value = num(message.modifiers);
  return Number.isInteger(value) && value >= 0 && value < 16 ? value : 0;
};

// Linux/headless Chromium needs commands for Cmd editing shortcuts and Ctrl copy/cut.
const editingCommand = (key: string, modifiers: number) => {
  const modifier = modifiers & 0b0111;
  if (modifier !== 2 && modifier !== 4) return null;
  const lower = key.toLowerCase();
  const command =
    lower === "c"
      ? "copy"
      : lower === "x"
        ? "cut"
        : modifier !== 4
          ? null
          : lower === "a"
            ? "selectAll"
            : lower === "z"
              ? modifiers & 8
                ? "redo"
                : "undo"
              : null;
  return command ? { commands: [command] } : null;
};

const invalid = (message: string) => new OperationError("invalid_argument", message);

const optString = (params: Record<string, unknown>, key: string): string | undefined => {
  const value = params[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") throw invalid(`${key} must be a string.`);
  return value;
};

const optNumber = (params: Record<string, unknown>, key: string): number | undefined => {
  const value = params[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "number" || !Number.isFinite(value)) throw invalid(`${key} must be a number.`);
  return value;
};

const optBoolean = (params: Record<string, unknown>, key: string): boolean | undefined => {
  const value = params[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "boolean") throw invalid(`${key} must be true or false.`);
  return value;
};

const optStrings = (params: Record<string, unknown>, key: string): Array<string> | undefined => {
  const value = params[key];
  if (value === undefined || value === null) return undefined;
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string"))
    throw invalid(`${key} must be a list of strings.`);
  return value as Array<string>;
};

const remainingMs = (deadlineMs: number) => Math.max(1, Math.floor(deadlineMs - performance.now()));

const timeoutOf = (params: Record<string, unknown>) => {
  const value = optNumber(params, "timeoutMs");
  if (value === undefined) return BrowserPage.DEFAULT_TIMEOUT_MS;
  return Math.min(MAX_TIMEOUT_MS, Math.max(1, Math.round(value)));
};

const targetOf = (params: Record<string, unknown>): Target => ({
  ref: optString(params, "ref"),
  selector: optString(params, "selector"),
});

const hasTarget = (target: Target) => target.ref !== undefined || target.selector !== undefined;

const dialogPending = () =>
  new OperationError(
    "dialog_pending",
    "A browser dialog is pending. Read browser_status and use browser_dialog first.",
  );

class DownloadStarted extends OperationError {}

export class BrowserService {
  private readonly context: BrowserContext;
  private readonly sessionsRoot: string;
  private readonly log: Log;
  private readonly chats = new Map<string, ChatState>();
  private readonly pageTabs = new WeakMap<Page, Tab>();
  // Frame and target ids of each chat's pages, so a download in any frame or popup finds its chat.
  private readonly frameChats = new Map<string, ChatState>();
  private readonly activeDownloads = new Map<string, ActiveDownload>();
  private browserSession: CDPSession | null = null;
  private downloadDir = "";
  private tabCounter = 0;
  private pointerSequence = 0;

  constructor(options: { context: BrowserContext; sessionsRoot: string; log: Log }) {
    this.context = options.context;
    this.sessionsRoot = options.sessionsRoot;
    this.log = options.log;
  }

  async start() {
    const browser = this.context.browser();
    if (!browser) throw new Error("The browser context has no browser.");
    this.downloadDir = await NodeFSP.mkdtemp(NodePath.join(NodeOS.tmpdir(), "onyx-browser-downloads-"));
    const session = await browser.newBrowserCDPSession();
    this.browserSession = session;
    session.on("Target.targetCreated", ({ targetInfo }) => {
      const { openerId, openerFrameId, parentId, parentFrameId } = targetInfo;
      for (const owner of [openerFrameId, openerId, parentFrameId, parentId]) {
        const chat = owner === undefined ? undefined : this.frameChats.get(owner);
        if (!chat) continue;
        this.frameChats.set(targetInfo.targetId, chat);
        return;
      }
    });
    session.on("Target.targetDestroyed", ({ targetId }) => this.frameChats.delete(targetId));
    session.on("Browser.downloadWillBegin", (event) => this.beginDownload(event));
    session.on("Browser.downloadProgress", (event) => void this.trackDownload(event));
    await session.send("Target.setDiscoverTargets", { discover: true });
    // Downloads go to a directory this service owns, so it sees every download, also one that
    // starts in a popup before the popup is a tab.
    await session.send("Browser.setDownloadBehavior", {
      behavior: "allowAndName",
      downloadPath: this.downloadDir,
      eventsEnabled: true,
    });
    // Pages that a chat's tab opens belong to that chat; pages with no owner are ignored.
    this.context.on("page", (page) => {
      void page
        .opener()
        .then((opener) => {
          const owner = opener ? this.pageTabs.get(opener) : undefined;
          if (owner) return this.adoptPopup(owner, page);
        })
        .catch((error: unknown) => this.log("popup_adopt_failed", { error: String(error) }));
    });
  }

  // ---- connections ----

  handleConnection(socket: Socket) {
    let hello = false;
    let viewer: Viewer | null = null;
    const helloTimer = setTimeout(() => {
      if (!hello) socket.destroy();
    }, HELLO_TIMEOUT_MS);
    socket.on("error", (error) => this.log("socket_error", { error: error.message }));
    // A call client may half-close after its request and still read the reply.
    socket.on("end", () => {
      if (viewer || !hello) socket.destroy();
    });
    socket.on("close", () => {
      clearTimeout(helloTimer);
      if (viewer) void this.detachViewer(viewer);
    });
    readMessages(
      socket,
      (message: Message) => {
        if (message.kind !== KIND_JSON) throw new Error("Clients send only JSON frames.");
        const value = message.value;
        if (viewer) {
          this.onViewerMessage(viewer, value);
          return;
        }
        if (hello) throw new Error("An agent call takes one message.");
        hello = true;
        clearTimeout(helloTimer);
        if (value.op === "call") {
          void this.answerCall(socket, value);
        } else if (value.op === "view") {
          viewer = this.attachViewer(socket, value);
        } else {
          throw new Error("The hello must have op call or view.");
        }
      },
      (error) => this.log("connection_closed", { reason: error.message }),
    );
  }

  private async answerCall(socket: Socket, hello: Record<string, unknown>) {
    const method = typeof hello.method === "string" ? hello.method : "";
    const started = Date.now();
    let reply: unknown;
    let chat: string | null = null;
    try {
      if (typeof hello.chat !== "string" || !CHAT_ID_PATTERN.test(hello.chat))
        throw invalid("chat must be a lowercase UUID.");
      chat = hello.chat;
      const params = hello.params === undefined ? {} : asRecord(hello.params);
      if (params === null) throw invalid("params must be an object.");
      const timeoutMs = timeoutOf(params);
      let timer: ReturnType<typeof setTimeout> | undefined;
      const guard = new Promise<never>((_, reject) => {
        timer = setTimeout(
          () => reject(new OperationError("timeout", `The browser did not answer within ${timeoutMs}ms.`)),
          timeoutMs + CALL_GRACE_MS,
        );
      });
      const work = this.call(this.chatFor(chat), method, params, timeoutMs);
      void work.catch(noop);
      const result = await Promise.race([work, guard]).finally(() => clearTimeout(timer));
      reply = { ok: true, result };
      this.log("call", { method, chat, ms: Date.now() - started, ok: true });
    } catch (cause) {
      const error = toOperationError(cause);
      reply = { ok: false, error: { code: error.code, message: error.message } };
      this.log("call", { method, chat, ms: Date.now() - started, ok: false, code: error.code, message: error.message });
    }
    let bytes = encodeJson(reply);
    if (bytes.length - 4 > MAX_FRAME_LENGTH) {
      this.log("call_reply_too_large", { method, chat, bytes: bytes.length });
      bytes = encodeJson({
        ok: false,
        error: { code: "failed", message: "The browser finished, but its reply was too large to return." },
      });
    }
    if (!socket.destroyed) socket.end(bytes);
  }

  private chatFor(id: string): ChatState {
    let chat = this.chats.get(id);
    if (!chat) {
      chat = { id, tabs: new Map(), current: null, viewers: new Set(), tabsScheduled: false, opening: 0, ...this.savedDownloads(id) };
      this.chats.set(id, chat);
    }
    return chat;
  }

  // ---- tabs ----

  private tabJson(tab: Tab): TabJson {
    return {
      id: tab.id,
      url: BrowserPage.withoutDataPayload(tab.page.url()).slice(0, MAX_TAB_URL_CHARS),
      title: tab.title,
      loading: tab.loading,
      controller: tab.control.controller !== null ? "human" : tab.agentUsed ? "agent" : "none",
      dialog: tab.dialog
        ? {
            type: tab.dialog.type(),
            message: tab.dialog.message().slice(0, MAX_DIALOG_MESSAGE_CHARS),
            origin: tab.dialogOrigin,
          }
        : null,
    };
  }

  private async freshTabJson(tab: Tab) {
    await this.refreshTitle(tab);
    if (tab.dialog) await Promise.race([tab.dialogOpened.promise, sleepUntil(Date.now() + STATUS_READ_MS)]);
    return this.tabJson(tab);
  }

  private async refreshTitle(tab: Tab) {
    if (tab.dialog || tab.closing) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const state = await Promise.race([
      BrowserPage.readPageState(tab.cdp).catch(() => null),
      new Promise<null>((resolve) => {
        timer = setTimeout(() => resolve(null), STATUS_READ_MS);
      }),
    ]).finally(() => clearTimeout(timer));
    if (state === null) return;
    if (state.title !== tab.title) {
      tab.title = state.title;
      this.scheduleTabs(tab.chat);
    }
    void this.watchTitle(tab, state.contextId);
  }

  // A title change fires no page event, so one watch per document reports
  // the next one (T3 ServerBrowser.ts watchTitle).
  private async watchTitle(tab: Tab, contextId: number) {
    const title = tab.title;
    if (tab.titleWatch?.contextId === contextId && tab.titleWatch.title === title) return;
    const watch = { contextId, title };
    tab.titleWatch = watch;
    const changed = await tab.cdp
      .send("Runtime.evaluate", { contextId: watch.contextId, expression: titleChange(title), awaitPromise: true })
      .then(
        ({ exceptionDetails }) => exceptionDetails === undefined,
        () => false,
      );
    if (tab.titleWatch !== watch) return;
    tab.titleWatch = null;
    if (changed && !tab.closing) await this.refreshTitle(tab);
  }

  private scheduleTabs(chat: ChatState) {
    if (chat.tabsScheduled) return;
    chat.tabsScheduled = true;
    setImmediate(() => {
      chat.tabsScheduled = false;
      for (const viewer of chat.viewers) this.sendTabs(viewer);
    });
  }

  private sendTabs(viewer: Viewer) {
    this.send(viewer, {
      type: "tabs",
      tabs: [...viewer.chat.tabs.values()].map((tab) => this.tabJson(tab)),
      selected: viewer.selected?.id ?? null,
    });
  }

  private async createTab(chat: ChatState, agentUsed: boolean): Promise<Tab> {
    if (chat.tabs.size + chat.opening >= CHAT_TAB_LIMIT)
      throw new OperationError(
        "tab_limit",
        `This chat already has ${CHAT_TAB_LIMIT} browser tabs open. Reuse an open tab.`,
      );
    chat.opening += 1;
    try {
      const page = await this.context.newPage();
      return await this.registerPage(chat, page, agentUsed).catch(async (error: unknown) => {
        await page.close().catch(noop);
        throw error;
      });
    } finally {
      chat.opening -= 1;
    }
  }

  private async adoptPopup(opener: Tab, popup: Page) {
    if (opener.closing || opener.chat.tabs.size + opener.chat.opening >= CHAT_TAB_LIMIT) {
      this.log("popup_closed", { chat: opener.chat.id, reason: opener.closing ? "opener closed" : "tab limit" });
      await popup.close().catch(noop);
      return;
    }
    opener.chat.opening += 1;
    const tab = await this.registerPage(opener.chat, popup, opener.agentUsed)
      .catch((error: unknown) => {
        this.log("popup_adopt_failed", { error: String(error) });
        void popup.close().catch(noop);
        return null;
      })
      .finally(() => {
        opener.chat.opening -= 1;
      });
    if (tab) this.log("popup_adopted", { chat: tab.chat.id, tab: tab.id, opener: opener.id });
  }

  private async registerPage(chat: ChatState, page: Page, agentUsed: boolean): Promise<Tab> {
    const cdp = await this.context.newCDPSession(page);
    const tab: Tab = {
      id: `t${++this.tabCounter}`,
      chat,
      page,
      cdp,
      control: new SessionControl(() => BrowserPage.invalidateRefs(page)),
      viewers: new Set(),
      dialog: null,
      dialogOrigin: null,
      dialogOpened: Promise.withResolvers(),
      fileChooser: null,
      loading: false,
      title: "",
      titleWatch: null,
      agentUsed,
      closing: false,
      captureLock: Promise.resolve(),
      capturing: 0,
      frames: new Set(),
    };
    // Page.frameNavigated fires for a new document only, not for a history rewrite (onyx.app
    // rewrites its URL after load): refs and the file chooser die with the document.
    cdp.on("Page.frameNavigated", ({ frame }) => {
      if (frame.parentId) return;
      BrowserPage.invalidateRefs(page);
      this.closeFileChooser(tab);
    });
    cdp.on("Page.frameAttached", ({ frameId }) => {
      tab.frames.add(frameId);
      this.frameChats.set(frameId, chat);
    });
    cdp.on("Page.frameDetached", ({ frameId, reason }) => {
      if (reason !== "remove") return;
      tab.frames.delete(frameId);
      this.frameChats.delete(frameId);
    });
    const { targetInfo } = await cdp.send("Target.getTargetInfo");
    this.frameChats.set(targetInfo.targetId, chat);
    await cdp.send("Page.enable");
    page.setDefaultTimeout(BrowserPage.DEFAULT_TIMEOUT_MS);
    page.setDefaultNavigationTimeout(BrowserPage.DEFAULT_TIMEOUT_MS);
    await page
      .setViewportSize(VIEWPORT)
      .catch((error: unknown) => this.log("viewport_failed", { chat: chat.id, tab: tab.id, error: String(error) }));
    const isMainNavigation = (request: { isNavigationRequest(): boolean; frame(): unknown }) => {
      try {
        return request.isNavigationRequest() && request.frame() === page.mainFrame();
      } catch {
        return false;
      }
    };
    page.on("request", (request) => {
      if (!isMainNavigation(request)) return;
      tab.loading = true;
      this.scheduleTabs(chat);
    });
    page.on("load", () => {
      tab.loading = false;
      this.scheduleTabs(chat);
      void this.refreshTitle(tab);
    });
    page.on("domcontentloaded", () => void this.refreshTitle(tab));
    page.on("framenavigated", (frame) => {
      if (frame !== page.mainFrame()) return;
      this.scheduleTabs(chat);
      void this.refreshTitle(tab);
    });
    page.on("requestfailed", (request) => {
      if (!isMainNavigation(request)) return;
      tab.loading = false;
      this.scheduleTabs(chat);
    });
    // Playwright's dialog event has no frame, and it can arrive before or after this one.
    cdp.on("Page.javascriptDialogOpening", ({ url }) => {
      tab.dialogOrigin = originOf(url);
      tab.dialogOpened.resolve();
      if (tab.dialog) this.scheduleTabs(chat);
    });
    // A navigation can close a dialog without us answering it.
    cdp.on("Page.javascriptDialogClosed", () => {
      tab.dialogOrigin = null;
      tab.dialogOpened.resolve();
      tab.dialogOpened = Promise.withResolvers();
      if (!tab.dialog) return;
      tab.dialog = null;
      this.broadcastControl(tab);
      void this.refreshTitle(tab);
    });
    page.on("dialog", (dialog) => {
      if (tab.closing && dialog.type() === "beforeunload") {
        void dialog.accept().catch(noop);
        return;
      }
      tab.dialog = dialog;
      this.broadcastControl(tab);
    });
    page.on("filechooser", (chooser) => void this.offerFileChooser(tab, chooser));
    // Playwright cannot use a crashed page again, so the tab closes.
    page.on("crash", () => {
      this.log("page_crashed", { chat: chat.id, tab: tab.id });
      this.closeTab(tab);
    });
    page.on("close", () => this.dropTab(tab));
    this.pageTabs.set(page, tab);
    chat.tabs.set(tab.id, tab);
    this.log("tab_opened", { chat: chat.id, tab: tab.id });
    this.scheduleTabs(chat);
    if (page.isClosed()) this.dropTab(tab);
    return tab;
  }

  private closeTab(tab: Tab) {
    tab.closing = true;
    void tab.page.close().catch(noop);
    this.dropTab(tab);
  }

  private dropTab(tab: Tab) {
    if (!tab.chat.tabs.has(tab.id)) return;
    tab.closing = true;
    const chat = tab.chat;
    chat.tabs.delete(tab.id);
    for (const frame of tab.frames) this.frameChats.delete(frame);
    void tab.control.close().catch(noop);
    tab.fileChooser = null;
    tab.dialog = null;
    this.log("tab_closed", { chat: chat.id, tab: tab.id });
    if (chat.current === tab.id) this.setCurrent(chat, [...chat.tabs.values()].at(-1) ?? null);
    const current = chat.current === null ? null : (chat.tabs.get(chat.current) ?? null);
    for (const viewer of chat.viewers) if (viewer.selected === tab) this.selectTab(viewer, current);
    this.scheduleTabs(chat);
  }

  /** Viewers that do not control their selected tab move to the chat's new current tab. */
  private setCurrent(chat: ChatState, tab: Tab | null) {
    const id = tab?.id ?? null;
    if (chat.current === id) return;
    chat.current = id;
    for (const viewer of chat.viewers) {
      const holding = viewer.selected !== null && viewer.selected.control.controller === viewer.id;
      if (!holding) this.selectTab(viewer, tab);
    }
  }

  private resolveTab(chat: ChatState, params: Record<string, unknown>): Tab {
    const id = optString(params, "tab");
    if (id !== undefined) {
      const tab = chat.tabs.get(id);
      if (!tab) throw new OperationError("tab_not_found", `Tab ${id.slice(0, MAX_ECHO_CHARS)} is not open in this chat.`);
      this.setCurrent(chat, tab);
      return tab;
    }
    const current = chat.current === null ? undefined : chat.tabs.get(chat.current);
    if (!current)
      throw new OperationError("tab_required", "No browser tab is open. Call browser_open first.");
    return current;
  }

  // ---- agent calls ----

  private async call(
    chat: ChatState,
    method: string,
    params: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<unknown> {
    const deadlineMs = performance.now() + timeoutMs;
    switch (method) {
      case "status": {
        const current = chat.current;
        const tabs = await Promise.all([...chat.tabs.values()].map((tab) => this.freshTabJson(tab)));
        return { tabs, current };
      }
      case "open":
        return this.open(chat, params, deadlineMs);
      case "navigate": {
        const tab = this.resolveTab(chat, params);
        const url = optString(params, "url");
        const history = optString(params, "history");
        if ((url === undefined) === (history === undefined))
          throw invalid("Pass exactly one of url or history.");
        if (history !== undefined && !["back", "forward", "reload"].includes(history))
          throw invalid("history must be back, forward or reload.");
        const target =
          url === undefined ? { history: history as HistoryStep } : { url: normalizeUrl(url) };
        await this.agentWrite(tab, deadlineMs, () => this.navigate(tab, target, "load", remainingMs(deadlineMs)));
        return { tab: await this.freshTabJson(tab) };
      }
      case "snapshot": {
        const tab = this.resolveTab(chat, params);
        const screenshotPath = optString(params, "screenshotPath");
        const file =
          screenshotPath === undefined ? undefined : await resolveInChat(this.sessionsRoot, chat.id, screenshotPath);
        const text = await this.agentRead(tab, deadlineMs, async () => {
          const snapshot = await BrowserPage.snapshot(tab.page, tab.cdp);
          if (file !== undefined) {
            const png = await this.withScreencastsPaused(tab, () =>
              BrowserPage.captureViewport(tab.cdp, { format: "png" }),
            );
            await NodeFSP.mkdir(NodePath.dirname(file), { recursive: true });
            await NodeFSP.writeFile(file, Buffer.from(png, "base64"));
          }
          return `Title: ${snapshot.title}\nURL: ${snapshot.url}\n\n${snapshot.tree}`.slice(
            0,
            BrowserPage.MAX_SNAPSHOT_CHARS,
          );
        });
        return { tab: await this.freshTabJson(tab), text };
      }
      case "act": {
        const tab = this.resolveTab(chat, params);
        const message = await this.agentWrite(tab, deadlineMs, () =>
          this.act(tab, params, deadlineMs),
        );
        return {
          tab: await this.freshTabJson(tab),
          ...(message === undefined ? {} : { message }),
        };
      }
      case "evaluate": {
        const tab = this.resolveTab(chat, params);
        const expression = optString(params, "expression");
        if (expression === undefined || expression.trim() === "") throw invalid("expression is required.");
        const value = await this.agentWrite(tab, deadlineMs, () =>
          BrowserPage.evaluate(tab.cdp, expression, remainingMs(deadlineMs)),
        );
        return { value };
      }
      case "waitFor": {
        const tab = this.resolveTab(chat, params);
        const input = {
          ...targetOf(params),
          text: optString(params, "text"),
          urlIncludes: optString(params, "urlIncludes"),
        };
        if (!hasTarget(input) && input.text === undefined && input.urlIncludes === undefined)
          throw invalid("Pass ref, selector, text or urlIncludes.");
        await this.agentRead(tab, deadlineMs, () =>
          BrowserPage.waitFor(tab.page, { ...input, timeoutMs: remainingMs(deadlineMs) }),
        );
        return { tab: await this.freshTabJson(tab) };
      }
      case "dialog": {
        const tab = this.resolveTab(chat, params);
        const accept = optBoolean(params, "accept");
        if (accept === undefined) throw invalid("accept is required.");
        // Resolved outside the queue so it can unblock an action waiting on the dialog.
        if (tab.control.controller !== null)
          throw new OperationError("human_control", HUMAN_CONTROL_MESSAGE);
        await this.resolveDialog(tab, accept, optString(params, "promptText"));
        return { tab: await this.freshTabJson(tab) };
      }
      default:
        throw invalid(`Unknown method ${method.slice(0, MAX_ECHO_CHARS)}.`);
    }
  }

  private async open(chat: ChatState, params: Record<string, unknown>, deadlineMs: number) {
    const rawUrl = optString(params, "url");
    const url = rawUrl === undefined ? undefined : normalizeUrl(rawUrl);
    const newTab = optBoolean(params, "newTab") ?? false;
    const existing = newTab || chat.current === null ? undefined : chat.tabs.get(chat.current);
    if (existing) {
      await this.agentWrite(existing, deadlineMs, async () => {
        if (url !== undefined)
          await this.navigate(existing, { url }, "domcontentloaded", remainingMs(deadlineMs));
      });
      return { tab: await this.freshTabJson(existing) };
    }
    const tab = await this.createTab(chat, true);
    this.setCurrent(chat, tab);
    if (url !== undefined && url !== "about:blank") {
      try {
        await this.agentWrite(tab, deadlineMs, () =>
          this.navigate(tab, { url }, "domcontentloaded", remainingMs(deadlineMs)),
        );
      } catch (cause) {
        // A failed open returns no tab; the download case keeps it so the file saves.
        if (!(cause instanceof DownloadStarted))
          this.closeTab(tab);
        throw cause;
      }
    }
    return { tab: await this.freshTabJson(tab) };
  }

  /** Agent writes need the tab free of human control and dialogs. */
  private agentWrite<A>(tab: Tab, deadlineMs: number, run: () => Promise<A>): Promise<A> {
    if (tab.dialog) return Promise.reject(dialogPending());
    return tab.control.agent(async () => {
      if (tab.dialog) throw dialogPending();
      if (!tab.agentUsed) {
        tab.agentUsed = true;
        this.broadcastControl(tab);
      }
      return run();
    }, deadlineMs);
  }

  /** Reads queue behind agent work, but run at once while a human controls the tab. */
  private agentRead<A>(tab: Tab, deadlineMs: number, run: () => Promise<A>): Promise<A> {
    const guarded = async () => {
      if (tab.dialog) throw dialogPending();
      return run();
    };
    if (tab.control.controller !== null) return tab.control.observe(guarded);
    return tab.control.agent(guarded, deadlineMs).catch((cause: unknown) => {
      if (cause instanceof BrowserControlInterrupted && cause.reason !== "closed")
        return tab.control.observe(guarded);
      throw cause;
    });
  }

  private leaveBusyPage(tab: Tab, cdp: CDPSession, budgetMs?: number) {
    return tab.dialog ? Promise.resolve() : BrowserPage.stopUnresponsiveScript(cdp, budgetMs);
  }

  private async navigate(
    tab: Tab,
    target: { readonly url: string } | { readonly history: HistoryStep },
    readiness: "load" | "domcontentloaded",
    timeout: number,
  ) {
    const startedAt = performance.now();
    const remaining = () => Math.max(1, timeout - (performance.now() - startedAt));
    await this.leaveBusyPage(tab, tab.cdp, timeout / 2);
    const options = { timeout: remaining(), waitUntil: "commit" } as const;
    const navigation =
      "url" in target
        ? tab.page.goto(target.url, options)
        : target.history === "back"
          ? tab.page.goBack(options)
          : target.history === "forward"
            ? tab.page.goForward(options)
            : tab.page.reload(options);
    // Once the target commits, a stalled subresource only delays readiness; report the loading tab.
    const ready = () =>
      tab.page.waitForLoadState(readiness, { timeout: remaining() }).catch((cause: unknown) => {
        if (!isTimeout(cause)) throw cause;
      });
    await navigation.then(ready).catch((cause: unknown) => {
      throw this.navigationError("url" in target ? target.url : tab.page.url(), cause, timeout);
    });
  }

  /** Viewer navigations run unawaited; a failure reaches the viewer as an error message. */
  private trackViewerNavigation(tab: Tab, viewer: Viewer, navigation: Promise<unknown>, url?: string) {
    tab.control.trackUntilHandoff(
      navigation.catch((cause: unknown) => {
        // A newer navigation reports for itself.
        if (tab.closing || /interrupted by another navigation|ERR_ABORTED/.test(String(cause))) return;
        const error = this.navigationError(url ?? tab.page.url(), cause, VIEWER_NAVIGATION_OPTIONS.timeout);
        this.send(viewer, { type: "error", message: error.message });
      }),
    );
  }

  private navigationError(url: string, cause: unknown, timeout: number) {
    const message = cause instanceof Error ? cause.message : String(cause);
    if (message.includes("Download is starting"))
      return new DownloadStarted(
        "failed",
        `${url} started a download instead of a page; a saved download appears in the chat's downloads/ folder.`,
      );
    const netError = /ERR_[A-Z\d_]+/.exec(message)?.[0];
    if (netError) return new OperationError("failed", `Navigation to ${url} failed: ${netError}`);
    const error = toOperationError(cause);
    return error.code === "timeout"
      ? new OperationError("timeout", `Navigation did not commit within ${timeout}ms.`)
      : error;
  }

  private async act(
    tab: Tab,
    params: Record<string, unknown>,
    deadlineMs: number,
  ): Promise<string | undefined> {
    const action = optString(params, "action");
    const target = targetOf(params);
    // Time spent queued behind other work on this tab counts against the deadline.
    const timeoutMs = remainingMs(deadlineMs);
    const pointer = this.pointerFor(tab);
    switch (action) {
      case "click": {
        const x = optNumber(params, "x");
        const y = optNumber(params, "y");
        if (!hasTarget(target) && (x === undefined || y === undefined))
          throw invalid("click needs ref, selector, or x and y.");
        const button = optString(params, "button");
        if (button !== undefined && !["left", "right", "middle"].includes(button))
          throw invalid("button must be left, right or middle.");
        await BrowserPage.click(
          tab.page,
          {
            ...target,
            x,
            y,
            button: button as "left" | "right" | "middle" | undefined,
            clickCount: optNumber(params, "clickCount"),
            timeoutMs,
          },
          pointer,
        );
        return undefined;
      }
      case "type": {
        const text = optString(params, "text");
        if (text === undefined) throw invalid("type needs text.");
        await BrowserPage.type(tab.page, {
          ...target,
          text,
          clear: optBoolean(params, "clear"),
          timeoutMs,
        });
        return undefined;
      }
      case "hover": {
        const x = optNumber(params, "x");
        const y = optNumber(params, "y");
        if (!hasTarget(target) && (x === undefined || y === undefined))
          throw invalid("hover needs ref, selector, or x and y.");
        await BrowserPage.hover(tab.page, { ...target, x, y, timeoutMs }, pointer);
        return undefined;
      }
      case "select": {
        const values = optStrings(params, "values");
        if (!hasTarget(target) || values === undefined)
          throw invalid("select needs ref or selector, and values.");
        const selected = await BrowserPage.select(tab.page, { ...target, values, timeoutMs });
        return `Selected: ${selected.join(", ")}`;
      }
      case "drag": {
        const dropTarget: Target = { ref: optString(params, "targetRef") };
        if (!hasTarget(target) || !hasTarget(dropTarget))
          throw invalid("drag needs ref or selector, and targetRef.");
        await BrowserPage.drag(tab.page, { source: target, target: dropTarget, timeoutMs }, pointer);
        return undefined;
      }
      case "press": {
        const key = optString(params, "key");
        if (key === undefined || key === "") throw invalid("press needs key.");
        await BrowserPage.press(tab.page, { key, modifiers: optStrings(params, "modifiers") });
        return undefined;
      }
      case "scroll": {
        await BrowserPage.scroll(tab.page, {
          ...target,
          deltaX: optNumber(params, "deltaX"),
          deltaY: optNumber(params, "deltaY"),
        });
        return undefined;
      }
      case "upload": {
        const paths = optStrings(params, "paths");
        if (paths === undefined) throw invalid("upload needs paths.");
        const absolute = await Promise.all(paths.map((path) => resolveInChat(this.sessionsRoot, tab.chat.id, path)));
        await this.uploadFiles(tab, { ...target, paths: absolute, timeoutMs });
        return `Uploaded ${absolute.length} file${absolute.length === 1 ? "" : "s"}.`;
      }
      default:
        throw invalid("action must be click, type, hover, select, drag, press, scroll or upload.");
    }
  }

  private pointerFor(tab: Tab): BrowserPage.PointerReporter {
    return async ({ x, y }, phase) => {
      if (tab.viewers.size === 0) return;
      const show = (next: "move" | "click") => {
        const sequence = ++this.pointerSequence;
        for (const viewer of tab.viewers)
          this.send(viewer, { type: "pointer", phase: next, x, y, sequence });
      };
      show("move");
      await sleepUntil(Date.now() + AGENT_CURSOR_MOVE_MS);
      if (phase !== "click") return;
      show("click");
      await sleepUntil(Date.now() + AGENT_CURSOR_CLICK_LEAD_MS);
    };
  }

  private async resolveDialog(tab: Tab, accept: boolean, promptText?: string) {
    const dialog = tab.dialog;
    if (!dialog) throw new OperationError("failed", "No dialog is pending.");
    if (accept) await dialog.accept(promptText);
    else await dialog.dismiss();
    if (tab.dialog === dialog) tab.dialog = null;
    BrowserPage.invalidateRefs(tab.page);
    this.broadcastControl(tab);
  }

  private withCaptureLock<A>(tab: Tab, operation: () => Promise<A>): Promise<A> {
    const run = tab.captureLock.then(() => {
      if (tab.closing) throw new Error("The tab closed.");
      return operation();
    });
    tab.captureLock = run.then(noop, noop);
    return run;
  }

  private withScreencastsPaused<A>(tab: Tab, capture: () => Promise<A>): Promise<A> {
    return this.withCaptureLock(tab, async () => {
      tab.capturing += 1;
      try {
        await Promise.all([...tab.viewers].map((viewer) => this.pauseCast(viewer)));
        return await capture();
      } finally {
        tab.capturing -= 1;
        await Promise.all([...tab.viewers].map((viewer) => this.resumeCast(viewer)));
      }
    });
  }

  // ---- downloads and file chooser ----

  // A restarted service starts the budget from the downloads that the chat session restored.
  private savedDownloads(chat: string) {
    const dir = NodePath.join(chatDir(this.sessionsRoot, chat), "downloads");
    let names: Array<string> = [];
    try {
      names = NodeFS.readdirSync(dir);
    } catch {}
    const sizes = names.map((name) => NodeFS.lstatSync(NodePath.join(dir, name), { throwIfNoEntry: false })?.size ?? 0);
    return { downloads: sizes.length, downloadBytes: sizes.reduce((total, size) => total + size, 0) };
  }

  private cancelDownload(guid: string) {
    void this.browserSession
      ?.send("Browser.cancelDownload", { guid })
      .catch((error: unknown) => this.log("download_cancel_failed", { error: String(error) }));
  }

  private chatDownloadBytes(chat: ChatState) {
    let total = chat.downloadBytes;
    for (const download of this.activeDownloads.values())
      if (download.chat === chat) total += download.receivedBytes;
    return total;
  }

  private beginDownload({ guid, frameId, suggestedFilename }: DownloadStart) {
    const chat = this.frameChats.get(frameId);
    if (!chat || chat.downloads >= CHAT_DOWNLOAD_LIMIT || this.chatDownloadBytes(chat) >= DOWNLOAD_MAX_BYTES) {
      this.log("download_refused", { chat: chat?.id ?? null, reason: chat ? "over budget" : "no chat" });
      this.cancelDownload(guid);
      return;
    }
    chat.downloads += 1;
    this.activeDownloads.set(guid, { chat, fileName: suggestedFilename || "download", receivedBytes: 0 });
  }

  private async trackDownload({ guid, state, receivedBytes }: DownloadProgress) {
    const download = this.activeDownloads.get(guid);
    if (download) download.receivedBytes = receivedBytes;
    if (state === "inProgress") {
      if (download && this.chatDownloadBytes(download.chat) > DOWNLOAD_MAX_BYTES) {
        this.activeDownloads.delete(guid);
        download.chat.downloads -= 1;
        this.log("download_too_large", { chat: download.chat.id, size: receivedBytes });
        this.cancelDownload(guid);
      }
      return;
    }
    this.activeDownloads.delete(guid);
    const temporary = NodePath.join(this.downloadDir, guid);
    try {
      const saved = download !== undefined && state === "completed" && (await this.saveDownload(download, temporary));
      if (download && !saved) download.chat.downloads -= 1;
    } finally {
      await NodeFSP.rm(temporary, { force: true }).catch(noop);
    }
  }

  private async saveDownload(download: ActiveDownload, temporary: string): Promise<boolean> {
    const { chat, receivedBytes: size } = download;
    if (this.chatDownloadBytes(chat) + size > DOWNLOAD_MAX_BYTES) {
      this.log("download_too_large", { chat: chat.id, size });
      return false;
    }
    chat.downloadBytes += size;
    let path: string | null = null;
    try {
      const dir = await resolveInChat(this.sessionsRoot, chat.id, "downloads");
      const fileName = await reserveUniqueFile(dir, download.fileName);
      path = NodePath.join(dir, fileName);
      await NodeFSP.copyFile(temporary, path);
      this.log("download_saved", { chat: chat.id, fileName, size });
      for (const viewer of chat.viewers) this.send(viewer, { type: "download", fileName });
      return true;
    } catch (error) {
      chat.downloadBytes -= size;
      if (path !== null) await NodeFSP.rm(path, { force: true }).catch(noop);
      this.log("download_failed", { chat: chat.id, error: String(error) });
      return false;
    }
  }

  // Not isConnected: upload helpers often click an input never added to the page. The handle's
  // context is destroyed with its document, so a replaced document rejects.
  private isFileChooserCurrent(chooser: FileChooser) {
    return chooser
      .element()
      .evaluate(
        (element) =>
          (element as unknown as { ownerDocument: unknown }).ownerDocument ===
          (globalThis as unknown as { document: unknown }).document,
      )
      .catch(() => false);
  }

  private async offerFileChooser(tab: Tab, chooser: FileChooser) {
    const [current, frame] = await Promise.all([
      this.isFileChooserCurrent(chooser),
      chooser.element().ownerFrame().catch(() => null),
    ]);
    if (!current) return;
    this.closeFileChooser(tab);
    tab.fileChooser = {
      id: NodeCrypto.randomUUID(),
      chooser,
      origin: frame ? originOf(frame.url()) : null,
      offeredTo: null,
    };
    this.pushFileChooser(tab);
  }

  private pushFileChooser(tab: Tab) {
    const open = tab.fileChooser;
    const controller = [...tab.viewers].find((viewer) => viewer.id === tab.control.controller);
    if (!open || !controller) return;
    let current = open;
    if (open.offeredTo !== controller.id) {
      current = { ...open, id: NodeCrypto.randomUUID(), offeredTo: controller.id };
      tab.fileChooser = current;
      if (open.offeredTo !== null)
        for (const viewer of tab.viewers) this.send(viewer, { type: "fileChooserClosed", id: open.id });
    }
    this.send(controller, {
      type: "fileChooser",
      id: current.id,
      multiple: current.chooser.isMultiple(),
      origin: current.origin,
    });
  }

  private closeFileChooser(tab: Tab) {
    const open = tab.fileChooser;
    if (!open) return;
    tab.fileChooser = null;
    for (const viewer of tab.viewers) this.send(viewer, { type: "fileChooserClosed", id: open.id });
  }

  private async uploadFiles(tab: Tab, input: BrowserPage.UploadInput) {
    // A picker left open by an earlier click must not take a later untargeted upload.
    if (await BrowserPage.setInputFiles(tab.page, input)) {
      this.closeFileChooser(tab);
      return;
    }
    const open = tab.fileChooser;
    if (!open)
      throw new OperationError(
        "failed",
        "No file picker is open. Click the page's upload control first, or pass the file input's ref.",
      );
    if (input.paths.length > 1 && !open.chooser.isMultiple())
      throw new OperationError("invalid_argument", "This file picker accepts one file.");
    if (input.paths.length > 0)
      await open.chooser.setFiles([...input.paths], { timeout: input.timeoutMs });
    if (tab.fileChooser === open) this.closeFileChooser(tab);
  }

  // ---- viewers ----

  private send(viewer: Viewer, event: ViewerEvent) {
    this.write(viewer, encodeJson(event));
  }

  private write(viewer: Viewer, bytes: Buffer) {
    const socket = viewer.socket;
    if (socket.destroyed || viewer.closed) return;
    if (socket.writableLength + bytes.length > MAX_SOCKET_BUFFER_BYTES) {
      this.log("viewer_too_slow", { viewer: viewer.id });
      socket.destroy();
      return;
    }
    socket.write(bytes);
  }

  private controllerFor(viewer: Viewer): ViewerControl {
    const tab = viewer.selected;
    if (!tab) return "none";
    const owner = tab.control.controller;
    if (owner === viewer.id) return "you";
    if (owner !== null) return "another-viewer";
    return tab.agentUsed ? "agent" : "none";
  }

  private sendControl(viewer: Viewer) {
    this.send(viewer, { type: "control", controller: this.controllerFor(viewer) });
  }

  private broadcastControl(tab: Tab) {
    for (const viewer of tab.viewers) this.sendControl(viewer);
    this.pushFileChooser(tab);
    this.scheduleTabs(tab.chat);
  }

  private attachViewer(socket: Socket, hello: Record<string, unknown>): Viewer {
    const chatId = hello.chat;
    if (typeof chatId !== "string" || !CHAT_ID_PATTERN.test(chatId))
      throw new Error("chat must be a lowercase UUID.");
    const chat = this.chatFor(chatId);
    const viewer: Viewer = {
      id: NodeCrypto.randomUUID(),
      chat,
      socket,
      selected: null,
      cast: null,
      selecting: Promise.resolve(),
      inFlight: null,
      pending: null,
      pressedKeys: new Map(),
      pressedButtons: new Map(),
      closed: false,
    };
    chat.viewers.add(viewer);
    this.log("viewer_attached", { chat: chat.id, viewer: viewer.id });
    // No current tab (for example only tabs a viewer opened): the newest one.
    const initial =
      (chat.current === null ? undefined : chat.tabs.get(chat.current)) ??
      [...chat.tabs.values()].at(-1);
    this.sendTabs(viewer);
    this.sendControl(viewer);
    if (initial) this.selectTab(viewer, initial);
    return viewer;
  }

  private async detachViewer(viewer: Viewer) {
    if (viewer.closed) return;
    viewer.closed = true;
    viewer.chat.viewers.delete(viewer);
    this.log("viewer_detached", { chat: viewer.chat.id, viewer: viewer.id });
    viewer.pending?.ack();
    viewer.inFlight?.ack();
    viewer.pending = null;
    viewer.inFlight = null;
    await viewer.selecting.catch(noop);
    const cast = viewer.cast;
    for (const tab of viewer.chat.tabs.values()) {
      if (tab.control.controller !== viewer.id) continue;
      const release =
        cast && cast.tab === tab ? () => this.releaseViewerInput(viewer, cast.session) : undefined;
      await tab.control.disconnect(viewer.id, release).catch(noop);
      this.broadcastControl(tab);
    }
    if (viewer.selected) viewer.selected.viewers.delete(viewer);
    viewer.selected = null;
    await this.stopCast(viewer);
  }

  /** Serialized per viewer; the latest request wins. */
  private selectTab(viewer: Viewer, tab: Tab | null) {
    const run = viewer.selecting.then(async () => {
      if (viewer.closed || viewer.selected === tab) return;
      const old = viewer.selected;
      const oldCast = viewer.cast;
      if (old) old.viewers.delete(viewer);
      if (oldCast && (viewer.pressedKeys.size > 0 || viewer.pressedButtons.size > 0))
        await this.releaseViewerInput(viewer, oldCast.session);
      await this.stopCast(viewer);
      // A frame of the old tab must not show after the switch.
      viewer.pending?.ack();
      viewer.pending = null;
      viewer.selected = tab && !tab.closing ? tab : null;
      this.sendTabs(viewer);
      this.sendControl(viewer);
      if (!viewer.selected) return;
      viewer.selected.viewers.add(viewer);
      const size = viewer.selected.page.viewportSize() ?? VIEWPORT;
      this.send(viewer, { type: "viewport", width: size.width, height: size.height });
      this.pushFileChooser(viewer.selected);
      await this.startCast(viewer, viewer.selected);
    });
    viewer.selecting = run.catch((error: unknown) =>
      this.log("viewer_select_failed", { viewer: viewer.id, error: String(error) }),
    );
    return viewer.selecting;
  }

  private deliverFrame(viewer: Viewer, frame: Frame) {
    if (viewer.closed || viewer.socket.destroyed) {
      frame.ack();
      return;
    }
    if (viewer.inFlight === null) {
      viewer.inFlight = frame;
      this.write(viewer, encodeFrame(KIND_JPEG, frame.data));
      return;
    }
    // Never sent, but Chromium still waits for its ack.
    viewer.pending?.ack();
    viewer.pending = frame;
  }

  private onAck(viewer: Viewer) {
    const done = viewer.inFlight;
    const next = viewer.pending;
    viewer.inFlight = null;
    viewer.pending = null;
    done?.ack();
    if (next) this.deliverFrame(viewer, next);
  }

  private async startCast(viewer: Viewer, tab: Tab) {
    const session = await this.context.newCDPSession(tab.page);
    if (viewer.closed || viewer.selected !== tab) {
      await session.detach().catch(noop);
      return;
    }
    const cast: Cast = {
      session,
      tab,
      framesInFlight: 0,
      mayHaveDropped: false,
      settleTimer: null,
      params: Promise.resolve(),
      started: false,
      stopped: false,
    };
    viewer.cast = cast;
    session.on("Page.screencastFrame", (frame) => {
      if (cast.stopped) return;
      cast.started = true;
      if (cast.framesInFlight > 0) cast.mayHaveDropped = true;
      cast.framesInFlight += 1;
      const arrivedAt = Date.now();
      // Chromium may drop the final frame during a burst; send a still when it settles.
      if (cast.settleTimer !== null) clearTimeout(cast.settleTimer);
      cast.settleTimer = setTimeout(() => {
        cast.settleTimer = null;
        if (!cast.mayHaveDropped) return;
        cast.mayHaveDropped = false;
        void this.pushStill(viewer, cast);
      }, SCREENCAST_SETTLE_MS);
      this.deliverFrame(viewer, {
        data: Buffer.from(frame.data, "base64"),
        ack: () =>
          void sleepUntil(arrivedAt + SCREENCAST_ACK_PACE_MS)
            .then(() => {
              cast.framesInFlight -= 1;
              return session.send("Page.screencastFrameAck", { sessionId: frame.sessionId });
            })
            .catch(noop),
      });
    });
    await this.startScreencast(cast);
    // An idle page does not repaint for a new screencast, so the viewer starts from a still.
    if (!cast.started) void this.pushStill(viewer, cast);
  }

  private startScreencast(cast: Cast) {
    cast.params = cast.params.then(async () => {
      if (cast.stopped || cast.tab.capturing > 0) return;
      await cast.session.send("Page.stopScreencast").catch(noop);
      await cast.session
        .send("Page.startScreencast", {
          format: "jpeg",
          quality: VIEWER_QUALITY,
          maxWidth: VIEWPORT.width,
          maxHeight: VIEWPORT.height,
        })
        .catch((error: unknown) =>
          this.log("screencast_failed", { chat: cast.tab.chat.id, tab: cast.tab.id, error: String(error) }),
        );
    });
    return cast.params;
  }

  private pauseCast(viewer: Viewer) {
    const cast = viewer.cast;
    if (!cast) return Promise.resolve();
    cast.params = cast.params.then(() => cast.session.send("Page.stopScreencast").then(noop, noop));
    return cast.params;
  }

  private resumeCast(viewer: Viewer) {
    const cast = viewer.cast;
    return cast ? this.startScreencast(cast) : Promise.resolve();
  }

  private async stopCast(viewer: Viewer) {
    const cast = viewer.cast;
    if (!cast) return;
    viewer.cast = null;
    cast.stopped = true;
    if (cast.settleTimer !== null) clearTimeout(cast.settleTimer);
    await cast.params.catch(noop);
    await cast.session.send("Page.stopScreencast").catch(noop);
    await cast.session.detach().catch(noop);
  }

  private async pushStill(viewer: Viewer, cast: Cast) {
    const data = await this.withCaptureLock(cast.tab, () =>
      BrowserPage.captureViewport(cast.session, { format: "jpeg", quality: VIEWER_QUALITY }),
    ).catch(() => null);
    if (data && viewer.cast === cast) this.deliverFrame(viewer, { data: Buffer.from(data, "base64"), ack: noop });
  }

  private async releaseViewerInput(viewer: Viewer, session: CDPSession) {
    for (const { key, code } of viewer.pressedKeys.values()) {
      await session.send("Input.dispatchKeyEvent", { type: "keyUp", key, code }).catch(noop);
    }
    viewer.pressedKeys.clear();
    for (const [button, point] of viewer.pressedButtons) {
      await session
        .send("Input.dispatchMouseEvent", {
          type: "mouseReleased",
          button,
          ...point,
          buttons: 0,
          clickCount: 1,
        })
        .catch(noop);
    }
    viewer.pressedButtons.clear();
  }

  private onViewerMessage(viewer: Viewer, message: Record<string, unknown>) {
    if (message.type === "ack") {
      this.onAck(viewer);
      return;
    }
    void this.handleViewerInput(viewer, message).catch((cause: unknown) => {
      const error = toOperationError(cause);
      this.send(viewer, { type: "error", message: error.message });
      if (viewer.selected) this.sendControl(viewer);
    });
  }

  private async handleViewerInput(viewer: Viewer, message: Record<string, unknown>) {
    const chat = viewer.chat;
    switch (message.type) {
      case "selectTab": {
        const id = optString(message, "tab") ?? "";
        const tab = chat.tabs.get(id);
        if (!tab) throw new OperationError("tab_not_found", "That tab is not open in this chat.");
        await this.selectTab(viewer, tab);
        return;
      }
      case "newTab": {
        const raw = optString(message, "url");
        const url = raw !== undefined && raw.trim() !== "" ? normalizeUrl(raw) : undefined;
        const tab = await this.createTab(chat, false);
        // A viewer that left meanwhile was already released; it must not take the new tab.
        if (viewer.closed) return;
        await tab.control.take(viewer.id);
        await this.selectTab(viewer, tab);
        this.broadcastControl(tab);
        if (url !== undefined && url !== "about:blank")
          this.trackViewerNavigation(tab, viewer, tab.page.goto(url, VIEWER_NAVIGATION_OPTIONS), url);
        return;
      }
      case "closeTab": {
        const id = optString(message, "tab") ?? "";
        const tab = chat.tabs.get(id);
        if (!tab) throw new OperationError("tab_not_found", "That tab is not open in this chat.");
        const owner = tab.control.controller;
        if (owner !== null && owner !== viewer.id)
          throw new OperationError("human_control", "Another viewer controls this tab.");
        this.closeTab(tab);
        return;
      }
    }
    await viewer.selecting;
    const tab = viewer.selected;
    const cast = viewer.cast;
    if (!tab || !cast || cast.tab !== tab)
      throw new OperationError("tab_required", "No tab is selected.");
    switch (message.type) {
      case "takeControl": {
        const taking = tab.control.take(viewer.id);
        this.broadcastControl(tab);
        await taking;
        return;
      }
      case "releaseControl": {
        const releasing = tab.control.release(viewer.id, () =>
          this.releaseViewerInput(viewer, cast.session),
        );
        this.broadcastControl(tab);
        await releasing;
        return;
      }
      case "dialog": {
        if (tab.control.controller !== viewer.id)
          throw new OperationError("human_control", "Take control of this tab first.");
        const accept = optBoolean(message, "accept");
        if (accept === undefined) throw invalid("accept must be true or false.");
        await this.resolveDialog(tab, accept, optString(message, "promptText"));
        return;
      }
      case "fileChooser": {
        const open = tab.fileChooser;
        const paths = optStrings(message, "paths");
        if (paths === undefined) throw invalid("paths must be a list of strings.");
        // Checked again after the path checks: control can change meanwhile.
        const offered = () =>
          open !== null &&
          tab.fileChooser === open &&
          open.id === message.id &&
          open.offeredTo === viewer.id &&
          tab.control.controller === viewer.id;
        if (!offered()) throw new OperationError("failed", "That file picker is no longer open.");
        const files = await Promise.all(
          paths.map((path) => resolveInChat(this.sessionsRoot, chat.id, path)),
        );
        if (!open || !offered()) throw new OperationError("failed", "That file picker is no longer open.");
        if (files.length > 0)
          await open.chooser.setFiles(open.chooser.isMultiple() ? files : files.slice(0, 1));
        if (tab.fileChooser === open) this.closeFileChooser(tab);
        return;
      }
      case "mouse":
      case "wheel":
      case "key":
      case "text":
      case "navigate":
      case "history":
      case "reload":
        break;
      default:
        throw invalid(`Unknown message type ${String(message.type).slice(0, MAX_ECHO_CHARS)}.`);
    }
    const dispatch = async (input: Record<string, unknown>) => {
      await this.dispatchViewerInput(tab, cast.session, viewer, input);
    };
    if (
      message.type === "mouse" &&
      message.action === "move" &&
      message.button === "none" &&
      message.buttons === 0
    ) {
      await tab.control.humanLatest(viewer.id, `hover:${modifiersOf(message)}`, message, dispatch);
    } else if (message.type === "wheel") {
      // A reversal stays separate so scrolling clamped at an edge behaves as if unmerged.
      await tab.control.humanLatest(
        viewer.id,
        `wheel:${num(message.x)}:${num(message.y)}:${modifiersOf(message)}:${Math.sign(num(message.deltaX))}:${Math.sign(num(message.deltaY))}`,
        message,
        dispatch,
        (waiting, next) => ({
          ...next,
          deltaX: num(waiting.deltaX) + num(next.deltaX),
          deltaY: num(waiting.deltaY) + num(next.deltaY),
        }),
      );
    } else {
      await tab.control.human(viewer.id, () => dispatch(message));
    }
  }

  private async dispatchViewerInput(
    tab: Tab,
    session: CDPSession,
    viewer: Viewer,
    message: Record<string, unknown>,
  ) {
    const modifiers = modifiersOf(message);
    switch (message.type) {
      case "mouse": {
        const action = message.action;
        const type =
          action === "down" ? "mousePressed" : action === "up" ? "mouseReleased" : "mouseMoved";
        const button = ["none", "left", "middle", "right"].includes(String(message.button))
          ? (message.button as "none" | MouseButton)
          : "none";
        await session.send("Input.dispatchMouseEvent", {
          type,
          x: num(message.x),
          y: num(message.y),
          button,
          buttons: num(message.buttons),
          clickCount: num(message.clickCount, type === "mouseMoved" ? 0 : 1),
          modifiers,
        });
        if (button !== "none") {
          if (action === "down")
            viewer.pressedButtons.set(button, { x: num(message.x), y: num(message.y) });
          else if (action === "up") viewer.pressedButtons.delete(button);
        }
        return;
      }
      case "wheel":
        await session.send("Input.dispatchMouseEvent", {
          type: "mouseWheel",
          x: num(message.x),
          y: num(message.y),
          deltaX: num(message.deltaX),
          deltaY: num(message.deltaY),
          modifiers,
        });
        return;
      case "key": {
        const key = optString(message, "key") ?? "";
        const code = optString(message, "code") ?? "";
        const text = optString(message, "text");
        if (message.action === "up") {
          await session.send("Input.dispatchKeyEvent", { type: "keyUp", key, code, modifiers });
          viewer.pressedKeys.delete(code || key);
          return;
        }
        const command = editingCommand(key, modifiers);
        await session.send("Input.dispatchKeyEvent", {
          type: text ? "keyDown" : "rawKeyDown",
          key,
          code,
          modifiers,
          ...(text ? { text, unmodifiedText: text } : {}),
          ...command,
          windowsVirtualKeyCode: num(
            message.keyCode,
            key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0,
          ),
        });
        viewer.pressedKeys.set(code || key, { key, code });
        return;
      }
      case "text": {
        const text = optString(message, "text");
        if (text) await session.send("Input.insertText", { text: text.slice(0, MAX_INSERT_TEXT_CHARS) });
        return;
      }
      // A stalled navigation must not block a corrected URL or further viewer input.
      case "navigate": {
        const raw = optString(message, "url");
        if (raw !== undefined) {
          const url = normalizeUrl(raw);
          await this.leaveBusyPage(tab, session);
          this.trackViewerNavigation(tab, viewer, tab.page.goto(url, VIEWER_NAVIGATION_OPTIONS), url);
        }
        return;
      }
      case "history":
        await this.leaveBusyPage(tab, session);
        this.trackViewerNavigation(
          tab,
          viewer,
          num(message.delta) < 0
            ? tab.page.goBack(VIEWER_NAVIGATION_OPTIONS)
            : tab.page.goForward(VIEWER_NAVIGATION_OPTIONS),
        );
        return;
      case "reload":
        await this.leaveBusyPage(tab, session);
        this.trackViewerNavigation(tab, viewer, tab.page.reload(VIEWER_NAVIGATION_OPTIONS));
        return;
    }
  }
}
