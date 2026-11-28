/**
 * The state and transitions of the chat's right panel: its mode, its tabs,
 * width, Files search and seen files. The Files list, Sources and the
 * browser are fixed tabs, then the file tabs, so only the file tabs are
 * stored in order. Each fixed tab opens at most once and closes as any tab.
 * The browser's pages and its selected page come from its stream, not from
 * this state. The Files list and the file tabs follow the
 * output panel's shared tab rules; Sources and the browser stand apart.
 * The chat store applies the transitions per chat session; the shared view
 * applies them with useReducer.
 */
import {
  closePanelTab,
  movePanelTab,
  openPanelTab,
} from "@/lib/outputPanel/tabs";
import {
  DEFAULT_PANEL_PROPORTION,
  type OutputPanelMode,
} from "@/lib/outputPanel/layout";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { artifactKey, newestVersion } from "@/lib/chat/publishedFiles";

export const RIGHT_PANEL_FILES_TAB = "files";
export const RIGHT_PANEL_SOURCES_TAB = "sources";
export const RIGHT_PANEL_BROWSER_TAB = "browser";
const FILE_TAB_PREFIX = "file:";
// Session storage of each chat's panel width, as Craft keeps its panel's
export const CHAT_PANEL_STORAGE_PREFIX = "onyx:chat:output-panel:v1:";

/** The tab ID of a published file's artifact. */
export function rightPanelFileTab(
  file: Pick<PublishedFile, "artifact_id" | "file_id">
): string {
  return `${FILE_TAB_PREFIX}${artifactKey(file)}`;
}

/** The Files list or a file's tab, as opposed to Sources or the browser. */
function isFilesTab(tabId: string): boolean {
  return tabId !== RIGHT_PANEL_SOURCES_TAB && tabId !== RIGHT_PANEL_BROWSER_TAB;
}

/**
 * An open file tab: one per artifact. It shows the newest version of its
 * artifact that the chat knows, or, when pinned, the version it opened with.
 */
export interface ChatFileTab {
  file: PublishedFile;
  // Opened on an older version, from its reply card
  pinned: boolean;
}

// The shared tab rules take the Files list's ID and the open files
type FilesPanelTab = string | ChatFileTab;
const idOf = (tab: FilesPanelTab): string =>
  typeof tab === "string" ? tab : rightPanelFileTab(tab.file);
const isFile = (tab: FilesPanelTab): tab is ChatFileTab =>
  typeof tab !== "string";

export interface ChatRightPanelState {
  mode: OutputPanelMode;
  // The open file tabs, in order: each with the file that it opened with,
  // also when the Files list does not hold it
  fileTabs: ChatFileTab[];
  // The active tab: the Files list, Sources, the browser or a file tab
  activeId: string;
  // Whether the Files list and Sources have tabs
  filesOpen: boolean;
  sourcesOpen: boolean;
  // Whether the chat's browser is open in the panel: its pages show as tabs
  // and its view stays mounted. The browser selects the page that it shows.
  browserOpen: boolean;
  // The Files list and the open file tabs by most recent use. It picks the
  // tab after a closed one, and the tab that the panel toggle shows again.
  history: string[];
  // The panel's share of the workspace at medium size
  proportion: number;
  search: string;
  // Files the user has seen
  seenFileIds: string[];
  // Whether the panel has shown files yet. The files listed then count as
  // seen; files published later are new until opened.
  seenInitialized: boolean;
}

export const INITIAL_RIGHT_PANEL: ChatRightPanelState = {
  mode: "closed",
  fileTabs: [],
  activeId: RIGHT_PANEL_SOURCES_TAB,
  filesOpen: false,
  sourcesOpen: false,
  browserOpen: false,
  history: [],
  proportion: DEFAULT_PANEL_PROPORTION,
  search: "",
  seenFileIds: [],
  seenInitialized: false,
};

export type ChatRightPanelAction =
  // Shows the panel on the Files list, Sources, the open browser or an open
  // file tab
  | { type: "showTab"; tabId: string }
  // Opens the browser and shows it
  | { type: "openBrowser" }
  // Shows the panel on its last shown Files tab: the list or an open file
  | { type: "showFiles" }
  // Opens a file in its artifact's tab, pinned to its version or following
  // the newest
  | ({ type: "openFile" } & ChatFileTab)
  // Closes a tab. A closed active tab gives way to the last shown Files tab,
  // else Sources, else the browser; without one, the panel closes.
  | { type: "closeTab"; tabId: string }
  // Moves a file tab to another file tab's place, as a drop on that tab does
  | { type: "reorderTab"; tabId: string; overTabId: string }
  | { type: "closePanel" }
  // Closes the Sources tab, and the panel when Sources is the active tab
  | { type: "hideSources" }
  | { type: "setMode"; mode: Exclude<OutputPanelMode, "closed"> }
  | { type: "setProportion"; proportion: number }
  | { type: "setSearch"; search: string }
  // The panel shows files for the first time: the listed ones count as seen
  | { type: "initializeSeen"; fileIds: string[] }
  // The panel shows a file, such as a new version in its open tab
  | { type: "markSeen"; fileId: string };

// The Files list, while open, and the file tabs
function filesPanelTabs(state: ChatRightPanelState): FilesPanelTab[] {
  return state.filesOpen
    ? [RIGHT_PANEL_FILES_TAB, ...state.fileTabs]
    : state.fileTabs;
}

function activate(
  state: ChatRightPanelState,
  target: FilesPanelTab
): ChatRightPanelState {
  const mode = state.mode === "closed" ? "medium" : state.mode;
  if (target === RIGHT_PANEL_SOURCES_TAB || target === RIGHT_PANEL_BROWSER_TAB)
    return state.mode === mode &&
      state.activeId === target &&
      (target !== RIGHT_PANEL_SOURCES_TAB || state.sourcesOpen)
      ? state
      : {
          ...state,
          mode,
          activeId: target,
          sourcesOpen: state.sourcesOpen || target === RIGHT_PANEL_SOURCES_TAB,
        };
  const filesOpen = state.filesOpen || target === RIGHT_PANEL_FILES_TAB;
  const opened = openPanelTab<FilesPanelTab>(
    { tabs: filesPanelTabs({ ...state, filesOpen }), history: state.history },
    target,
    idOf
  );
  return {
    ...state,
    mode,
    filesOpen,
    // An open artifact's tab takes the version that opens it
    fileTabs: opened.tabs
      .filter(isFile)
      .map((tab) =>
        isFile(target) && idOf(tab) === idOf(target) ? target : tab
      ),
    activeId: idOf(target),
    history: opened.history,
  };
}

/**
 * The panel after its active tab closes: on the last shown Files tab, else
 * the first open one, else Sources, else the browser, else closed.
 */
function leaveClosedTab(state: ChatRightPanelState): ChatRightPanelState {
  const filesTab = filesPanelTabs(state)[0];
  const next =
    state.history[0] ??
    (filesTab !== undefined
      ? idOf(filesTab)
      : state.sourcesOpen
        ? RIGHT_PANEL_SOURCES_TAB
        : state.browserOpen
          ? RIGHT_PANEL_BROWSER_TAB
          : null);
  return next === null
    ? { ...state, mode: "closed" }
    : { ...state, activeId: next };
}

function isOpenFileTab(state: ChatRightPanelState, tabId: string): boolean {
  return state.fileTabs.some((file) => idOf(file) === tabId);
}

function markSeen(
  state: ChatRightPanelState,
  fileIds: string[]
): ChatRightPanelState {
  return fileIds.every((id) => state.seenFileIds.includes(id))
    ? state
    : {
        ...state,
        seenFileIds: [...new Set([...state.seenFileIds, ...fileIds])],
      };
}

export function rightPanelReducer(
  state: ChatRightPanelState,
  action: ChatRightPanelAction
): ChatRightPanelState {
  const open = state.mode !== "closed";
  switch (action.type) {
    case "showTab":
      return action.tabId === RIGHT_PANEL_FILES_TAB ||
        action.tabId === RIGHT_PANEL_SOURCES_TAB ||
        (action.tabId === RIGHT_PANEL_BROWSER_TAB && state.browserOpen) ||
        isOpenFileTab(state, action.tabId)
        ? activate(state, action.tabId)
        : state;
    case "openBrowser":
      return activate(
        state.browserOpen ? state : { ...state, browserOpen: true },
        RIGHT_PANEL_BROWSER_TAB
      );
    case "showFiles":
      // The history leads with the active tab when it is a Files tab
      return activate(state, state.history[0] ?? RIGHT_PANEL_FILES_TAB);
    case "openFile":
      // A file that opens the panel opens its Files list too
      return activate(
        {
          ...markSeen(state, [action.file.file_id]),
          filesOpen: state.filesOpen || !open,
        },
        {
          file: action.file,
          pinned: action.pinned,
        }
      );
    case "closeTab": {
      const active = open && state.activeId === action.tabId;
      if (
        action.tabId === RIGHT_PANEL_BROWSER_TAB ||
        action.tabId === RIGHT_PANEL_SOURCES_TAB
      ) {
        const browser = action.tabId === RIGHT_PANEL_BROWSER_TAB;
        if (!(browser ? state.browserOpen : state.sourcesOpen)) return state;
        const closed = browser
          ? { ...state, browserOpen: false }
          : { ...state, sourcesOpen: false };
        return active ? leaveClosedTab(closed) : closed;
      }
      if (
        !(action.tabId === RIGHT_PANEL_FILES_TAB
          ? state.filesOpen
          : isOpenFileTab(state, action.tabId))
      )
        return state;
      const closed = closePanelTab<FilesPanelTab>(
        {
          tabs: filesPanelTabs(state),
          activeId: state.activeId,
          history: state.history,
        },
        action.tabId,
        idOf
      );
      const next = {
        ...state,
        filesOpen: closed.tabs.includes(RIGHT_PANEL_FILES_TAB),
        fileTabs: closed.tabs.filter(isFile),
        history: closed.history,
      };
      if (!active) return next;
      return closed.activeId === null
        ? leaveClosedTab(next)
        : { ...next, activeId: closed.activeId };
    }
    case "reorderTab":
      return isOpenFileTab(state, action.tabId) &&
        isOpenFileTab(state, action.overTabId)
        ? {
            ...state,
            fileTabs: movePanelTab(
              state.fileTabs,
              action.tabId,
              state.fileTabs.findIndex(
                (file) => idOf(file) === action.overTabId
              ),
              idOf
            ),
          }
        : state;
    case "closePanel":
      return open ? { ...state, mode: "closed" } : state;
    case "hideSources":
      if (open && state.activeId === RIGHT_PANEL_SOURCES_TAB)
        return { ...state, mode: "closed", sourcesOpen: false };
      return state.sourcesOpen ? { ...state, sourcesOpen: false } : state;
    case "setMode":
      return open ? { ...state, mode: action.mode } : state;
    case "setProportion":
      return { ...state, proportion: action.proportion };
    case "setSearch":
      return { ...state, search: action.search };
    case "initializeSeen":
      return state.seenInitialized
        ? state
        : { ...markSeen(state, action.fileIds), seenInitialized: true };
    case "markSeen":
      return markSeen(state, [action.fileId]);
  }
}

/**
 * Opens a reply card's or an artifact link's file in its artifact's tab. The
 * tab is pinned to the file's version when `pinVersion` is set (a link that
 * names a version) or the chat's `files` hold a newer one; else it follows
 * the newest version. A card saved without an artifact whose file `files`
 * list opens the listed file, so the card and the file's tile share one tab.
 */
export function openCardFileAction(
  file: PublishedFile,
  files: readonly PublishedFile[],
  pinVersion = false
): ChatRightPanelAction {
  const opened =
    (file.artifact_id === null &&
      files.find((listed) => listed.file_id === file.file_id)) ||
    file;
  return {
    type: "openFile",
    file: opened,
    pinned: pinVersion || newestVersion(opened, files) !== opened,
  };
}

/** Whether the panel shows Sources, the browser, or a Files tab. */
export function showsSources(state: ChatRightPanelState): boolean {
  return state.mode !== "closed" && state.activeId === RIGHT_PANEL_SOURCES_TAB;
}
export function showsFiles(state: ChatRightPanelState): boolean {
  return state.mode !== "closed" && isFilesTab(state.activeId);
}
