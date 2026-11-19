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

/**
 * Whether a tab is the Files list or a shown file tab. A branch switch hides
 * the tabs of files off the branch; they stay open for a switch back.
 */
function isShownFilesTab(
  tabId: string,
  shownFileTabs: readonly string[]
): boolean {
  return tabId === RIGHT_PANEL_FILES_TAB || shownFileTabs.includes(tabId);
}

export interface ChatRightPanelState {
  mode: OutputPanelMode;
  // The open file tabs, in order
  fileTabs: string[];
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
  // panel. `shownFileTabs` are the open file tabs of files on the branch.
  | { type: "toggleFiles"; shownFileTabs: readonly string[] }
  // Opens a file in its own tab
  | { type: "openFile"; fileId: string }
  // Hands the active state to the last shown Files tab, as `toggleFiles`
  | { type: "closeTab"; tabId: string; shownFileTabs: readonly string[] }
  // Moves a file tab to another file tab's place, as a drop on that tab
  // does. Hidden tabs, of files off the branch, do not shift the move.
  | { type: "reorderTab"; tabId: string; overTabId: string }
  | { type: "closePanel" }
  // Closes the panel when Sources, or a Files tab, is the active tab
  | { type: "hideSources" }
  | { type: "hideFiles" }
  | { type: "setMode"; mode: Exclude<OutputPanelMode, "closed"> }
  | { type: "setProportion"; proportion: number }
  | { type: "setSearch"; search: string }
  // The panel shows files for the first time: the listed ones count as seen
  | { type: "initializeSeen"; fileIds: string[] };

// The shared tab rules take tabs of any kind; these tabs are their IDs
const idOf = (id: string): string => id;

function activate(state: ChatRightPanelState, id: string): ChatRightPanelState {
  const mode = state.mode === "closed" ? "medium" : state.mode;
  if (id === RIGHT_PANEL_SOURCES_TAB) return { ...state, mode, activeId: id };
  const opened = openPanelTab(
    {
      tabs: [RIGHT_PANEL_FILES_TAB, ...state.fileTabs],
      history: state.history,
    },
    id,
    idOf
  );
  return {
    ...state,
    mode,
    fileTabs: opened.tabs.slice(1),
    activeId: id,
    history: opened.history,
  };
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
        state.fileTabs.includes(action.tabId)
        ? activate(state, action.tabId)
        : state;
    case "toggleFiles":
      if (open && isFilesTab(state.activeId))
        return { ...state, mode: "closed" };
      // Reopening Files restores its last shown tab, the list or an open
      // file. The history leads with the active tab when it is a Files tab.
      return activate(
        state,
        state.history.find((tabId) =>
          isShownFilesTab(tabId, action.shownFileTabs)
        ) ?? RIGHT_PANEL_FILES_TAB
      );
    case "openFile":
      return activate(
        markSeen(state, [action.fileId]),
        rightPanelFileTab(action.fileId)
      );
    case "closeTab": {
      if (!state.fileTabs.includes(action.tabId)) return state;
      // The Files list leads the tabs, so it is the last tab left
      const closed = closePanelTab(
        {
          tabs: [RIGHT_PANEL_FILES_TAB, ...state.fileTabs],
          activeId: state.activeId,
          history: state.history,
        },
        action.tabId,
        idOf,
        (tabId) => isShownFilesTab(tabId, action.shownFileTabs)
      );
      return {
        ...state,
        fileTabs: closed.tabs.slice(1),
        activeId: closed.activeId ?? RIGHT_PANEL_FILES_TAB,
        history: closed.history,
      };
    }
    case "reorderTab":
      return state.fileTabs.includes(action.tabId) &&
        state.fileTabs.includes(action.overTabId)
        ? {
            ...state,
            fileTabs: movePanelTab(
              state.fileTabs,
              action.tabId,
              state.fileTabs.indexOf(action.overTabId),
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
    case "hideFiles":
      return open && isFilesTab(state.activeId)
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
