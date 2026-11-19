import {
  INITIAL_RIGHT_PANEL,
  RIGHT_PANEL_FILES_TAB,
  RIGHT_PANEL_SOURCES_TAB,
  rightPanelFileTab,
  rightPanelReducer,
  showsFiles,
  showsSources,
  type ChatRightPanelAction,
  type ChatRightPanelState,
} from "@/lib/chat/rightPanel";
import type { PublishedFile } from "@/app/app/services/streamingModels";

const FILE_A = rightPanelFileTab("a");
const FILE_B = rightPanelFileTab("b");
const FILE_C = rightPanelFileTab("c");

function apply(...actions: ChatRightPanelAction[]): ChatRightPanelState {
  return actions.reduce(rightPanelReducer, INITIAL_RIGHT_PANEL);
}

function file(fileId: string): PublishedFile {
  return {
    file_id: fileId,
    name: `${fileId}.md`,
    title: null,
    path: `/w/${fileId}.md`,
    display_path: `${fileId}.md`,
    size: 1,
    mime_type: "text/markdown",
  };
}

const openFile = (fileId: string): ChatRightPanelAction => ({
  type: "openFile",
  file: file(fileId),
});
const toggleFiles: ChatRightPanelAction = { type: "toggleFiles" };
const closeTab = (tabId: string): ChatRightPanelAction => ({
  type: "closeTab",
  tabId,
});
const tabIds = (state: ChatRightPanelState): string[] =>
  state.fileTabs.map((tab) => rightPanelFileTab(tab.file_id));

describe("rightPanelReducer", () => {
  test("the panel shows one tab at a time; closing the panel hides it, keeping its tabs", () => {
    let state = apply({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
    expect(showsSources(state)).toBe(true);
    state = rightPanelReducer(state, toggleFiles);
    expect(showsFiles(state)).toBe(true);
    expect(showsSources(state)).toBe(false);

    state = rightPanelReducer(state, { type: "closePanel" });
    expect(state.mode).toBe("closed");
    expect(state.activeId).toBe(RIGHT_PANEL_FILES_TAB);
  });

  test("closing the active file returns to the tab used before it", () => {
    let state = apply(openFile("a"), openFile("b"), openFile("c"));
    state = rightPanelReducer(state, { type: "showTab", tabId: FILE_A });
    state = rightPanelReducer(state, { type: "showTab", tabId: FILE_C });
    state = rightPanelReducer(state, closeTab(FILE_C));
    expect(state.activeId).toBe(FILE_A);
    expect(tabIds(state)).toEqual([FILE_A, FILE_B]);
  });

  test("the Files list and Sources cannot close or move", () => {
    const state = apply(openFile("a"));
    expect(rightPanelReducer(state, closeTab(RIGHT_PANEL_FILES_TAB))).toBe(
      state
    );
    expect(
      rightPanelReducer(state, {
        type: "reorderTab",
        tabId: RIGHT_PANEL_SOURCES_TAB,
        overTabId: FILE_A,
      })
    ).toBe(state);
  });

  test("a file tab moves to the place of the tab it drops on", () => {
    const state = apply(openFile("a"), openFile("b"), openFile("c"));

    // Forward: A takes B's place, after B
    const forward = rightPanelReducer(state, {
      type: "reorderTab",
      tabId: FILE_A,
      overTabId: FILE_B,
    });
    expect(tabIds(forward)).toEqual([FILE_B, FILE_A, FILE_C]);
    // Back: C takes B's place, before B
    const back = rightPanelReducer(forward, {
      type: "reorderTab",
      tabId: FILE_C,
      overTabId: FILE_B,
    });
    expect(tabIds(back)).toEqual([FILE_C, FILE_B, FILE_A]);
  });

  test("the files listed when the panel first shows files are seen; later ones once opened", () => {
    // A card opens a file before the panel lists the others
    let state = apply(openFile("b"));
    expect(state.seenFileIds).toEqual(["b"]);
    state = rightPanelReducer(state, {
      type: "initializeSeen",
      fileIds: ["a", "b", "c"],
    });
    expect(state.seenFileIds).toEqual(["b", "a", "c"]);
    // Only the first showing marks the listed files
    expect(
      rightPanelReducer(state, {
        type: "initializeSeen",
        fileIds: ["a", "b", "c", "d"],
      })
    ).toBe(state);
    expect(rightPanelReducer(state, openFile("d")).seenFileIds).toContain("d");
  });

  test("closing the last file tab shows the Files list, also after Sources", () => {
    let state = apply(
      { type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB },
      openFile("a")
    );
    state = rightPanelReducer(state, closeTab(FILE_A));
    expect(state.activeId).toBe(RIGHT_PANEL_FILES_TAB);
    expect(state.fileTabs).toEqual([]);
  });

  test("the Files button restores the last Files tab after Sources", () => {
    let state = apply(openFile("a"), {
      type: "showTab",
      tabId: RIGHT_PANEL_FILES_TAB,
    });
    state = rightPanelReducer(state, {
      type: "showTab",
      tabId: RIGHT_PANEL_SOURCES_TAB,
    });
    state = rightPanelReducer(state, toggleFiles);
    expect(state.activeId).toBe(RIGHT_PANEL_FILES_TAB);
  });

  test("hiding Sources closes the panel only when Sources is active", () => {
    const files = apply(toggleFiles);
    expect(rightPanelReducer(files, { type: "hideSources" })).toBe(files);

    const sources = apply({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
    expect(rightPanelReducer(sources, { type: "hideSources" }).mode).toBe(
      "closed"
    );
  });

  test("full size ends when the panel closes", () => {
    let state = apply(toggleFiles, { type: "setMode", mode: "full" });
    expect(state.mode).toBe("full");
    state = rightPanelReducer(state, { type: "closePanel" });
    state = rightPanelReducer(state, toggleFiles);
    expect(state.mode).toBe("medium");
  });
});
