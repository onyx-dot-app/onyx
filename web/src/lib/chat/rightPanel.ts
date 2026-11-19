/**
 * The state and transitions of the chat's right panel: its mode, its tabs,
 * width, Files search and seen files. The Files list and Sources are fixed
 * tabs before the file tabs, so only the file tabs are stored in order. The
 * Files list and the file tabs follow the output panel's shared tab rules;
 * Sources stands apart. The chat store applies the transitions per chat
 * session; the shared view applies them with useReducer.
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

export const RIGHT_PANEL_FILES_TAB = "files";
export const RIGHT_PANEL_SOURCES_TAB = "sources";
const FILE_TAB_PREFIX = "file:";
// Session storage of each chat's panel width, as Craft keeps its panel's
export const CHAT_PANEL_STORAGE_PREFIX = "onyx:chat:output-panel:v1:";

export function rightPanelFileTab(fileId: string): string {
  return `${FILE_TAB_PREFIX}${fileId}`;
}

/** The Files list or a file's tab, as opposed to Sources. */
function isFilesTab(tabId: string): boolean {
  return tabId !== RIGHT_PANEL_SOURCES_TAB;
}

// The shared tab rules take the Files list's ID and the open files
type FilesPanelTab = string | PublishedFile;
const idOf = (tab: FilesPanelTab): string =>
  typeof tab === "string" ? tab : rightPanelFileTab(tab.file_id);
const isFile = (tab: FilesPanelTab): tab is PublishedFile =>
  typeof tab !== "string";

export interface ChatRightPanelState {
  mode: OutputPanelMode;
  // The files of the open file tabs, in order: each the file that it opened
  // with, also when the Files list does not hold it
  fileTabs: PublishedFile[];
  // The active tab: the Files list, Sources or a file tab
  activeId: string;
  // The Files list and the open file tabs by most recent use. It picks the
  // tab after a closed one, and the tab that the Files button shows again.
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
  history: [],
  proportion: DEFAULT_PANEL_PROPORTION,
  search: "",
  seenFileIds: [],
  seenInitialized: false,
};

export type ChatRightPanelAction =
  // Shows the panel on the Files list, Sources or an open file tab
  | { type: "showTab"; tabId: string }
  // The Files button: shows the panel's last shown Files tab, or closes the
  // panel
  | { type: "toggleFiles" }
  // Opens a file in its own tab
  | { type: "openFile"; file: PublishedFile }
  // Hands the active state to the last shown Files tab, as `toggleFiles`
  | { type: "closeTab"; tabId: string }
  // Moves a file tab to another file tab's place, as a drop on that tab does
  | { type: "reorderTab"; tabId: string; overTabId: string }
  | { type: "closePanel" }
  // Closes the panel when Sources is the active tab
  | { type: "hideSources" }
  | { type: "setMode"; mode: Exclude<OutputPanelMode, "closed"> }
  | { type: "setProportion"; proportion: number }
  | { type: "setSearch"; search: string }
  // The panel shows files for the first time: the listed ones count as seen
  | { type: "initializeSeen"; fileIds: string[] };

function activate(
  state: ChatRightPanelState,
  target: FilesPanelTab
): ChatRightPanelState {
  const mode = state.mode === "closed" ? "medium" : state.mode;
  if (target === RIGHT_PANEL_SOURCES_TAB)
    return { ...state, mode, activeId: target };
  const opened = openPanelTab<FilesPanelTab>(
    {
      tabs: [RIGHT_PANEL_FILES_TAB, ...state.fileTabs],
      history: state.history,
    },
    target,
    idOf
  );
  return {
    ...state,
    mode,
    fileTabs: opened.tabs.filter(isFile),
    activeId: idOf(target),
    history: opened.history,
  };
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
        isOpenFileTab(state, action.tabId)
        ? activate(state, action.tabId)
        : state;
    case "toggleFiles":
      if (open && isFilesTab(state.activeId))
        return { ...state, mode: "closed" };
      // Reopening Files restores its last shown tab, the list or an open
      // file. The history leads with the active tab when it is a Files tab.
      return activate(state, state.history[0] ?? RIGHT_PANEL_FILES_TAB);
    case "openFile":
      return activate(markSeen(state, [action.file.file_id]), action.file);
    case "closeTab": {
      if (!isOpenFileTab(state, action.tabId)) return state;
      // The Files list leads the tabs, so it is the last tab left
      const closed = closePanelTab<FilesPanelTab>(
        {
          tabs: [RIGHT_PANEL_FILES_TAB, ...state.fileTabs],
          activeId: state.activeId,
          history: state.history,
        },
        action.tabId,
        idOf
      );
      return {
        ...state,
        fileTabs: closed.tabs.filter(isFile),
        activeId: closed.activeId ?? RIGHT_PANEL_FILES_TAB,
        history: closed.history,
      };
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
      return open && state.activeId === RIGHT_PANEL_SOURCES_TAB
        ? { ...state, mode: "closed" }
        : state;
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
  }
}

/** Whether the panel shows Sources, or a Files tab. */
export function showsSources(state: ChatRightPanelState): boolean {
  return state.mode !== "closed" && state.activeId === RIGHT_PANEL_SOURCES_TAB;
}
export function showsFiles(state: ChatRightPanelState): boolean {
  return state.mode !== "closed" && isFilesTab(state.activeId);
}
