import {
  INITIAL_RIGHT_PANEL,
  RIGHT_PANEL_FILES_TAB,
  openCardFileAction,
  RIGHT_PANEL_SOURCES_TAB,
  rightPanelFileTab,
  rightPanelReducer,
  showsFiles,
  showsSources,
  type ChatRightPanelAction,
  type ChatRightPanelState,
} from "@/lib/chat/rightPanel";
import type { PublishedFile } from "@/app/app/services/streamingModels";

function apply(...actions: ChatRightPanelAction[]): ChatRightPanelState {
  return actions.reduce(rightPanelReducer, INITIAL_RIGHT_PANEL);
}

// Version `version` of artifact `artifactId`
function file(artifactId: string, version = 1): PublishedFile {
  return {
    file_id: version === 1 ? artifactId : `${artifactId}-v${version}`,
    name: `${artifactId}.md`,
    title: null,
    path: `/w/${artifactId}.md`,
    display_path: `${artifactId}.md`,
    size: 1,
    mime_type: "text/markdown",
    artifact_id: `artifact-${artifactId}`,
    version,
    thumbnail_file_id: null,
  };
}

const FILE_A = rightPanelFileTab(file("a"));
const FILE_B = rightPanelFileTab(file("b"));
const FILE_C = rightPanelFileTab(file("c"));

const openFile = (
  artifactId: string,
  version = 1,
  pinned = false
): ChatRightPanelAction => ({
  type: "openFile",
  file: file(artifactId, version),
  pinned,
});
const showFiles: ChatRightPanelAction = { type: "showFiles" };
const closeTab = (tabId: string): ChatRightPanelAction => ({
  type: "closeTab",
  tabId,
});
const tabIds = (state: ChatRightPanelState): string[] =>
  state.fileTabs.map((tab) => rightPanelFileTab(tab.file));

describe("rightPanelReducer", () => {
  test("the panel shows one tab at a time; closing the panel hides it, keeping its tabs", () => {
    let state = apply({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
    expect(showsSources(state)).toBe(true);
    state = rightPanelReducer(state, {
      type: "showTab",
      tabId: RIGHT_PANEL_FILES_TAB,
    });
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

  test("an artifact has one tab, which takes the version that opens it", () => {
    let state = apply(openFile("a", 1), openFile("b"));
    // An older card pins the tab to its version, in the tab's place
    state = rightPanelReducer(state, openFile("a", 2, true));
    expect(tabIds(state)).toEqual([FILE_A, FILE_B]);
    expect(state.activeId).toBe(FILE_A);
    expect(state.fileTabs[0]).toEqual({ file: file("a", 2), pinned: true });
    // A tile follows the newest again
    state = rightPanelReducer(state, openFile("a", 3));
    expect(state.fileTabs[0]).toEqual({ file: file("a", 3), pinned: false });
    expect(state.seenFileIds).toEqual(["a", "b", "a-v2", "a-v3"]);
  });

  test("a file saved without an artifact has its own tab", () => {
    const unversioned = { ...file("a"), artifact_id: null, version: null };
    const state = apply(openFile("a"), {
      type: "openFile",
      file: unversioned,
      pinned: false,
    });
    expect(tabIds(state)).toEqual([FILE_A, rightPanelFileTab(unversioned)]);
  });

  test("a reply card pins its tab only to an older version", () => {
    const files = [file("a", 2), file("b")];
    expect(openCardFileAction(file("a", 1), files)).toEqual(
      openFile("a", 1, true)
    );
    expect(openCardFileAction(file("a", 2), files)).toEqual(
      openFile("a", 2, false)
    );
  });

  test("a card saved without an artifact opens the tab of its listed file", () => {
    const files = [file("a"), file("b")];
    const card = { ...file("a"), artifact_id: null, version: null };
    // The card shares the tile's tab
    expect(openCardFileAction(card, files)).toEqual(openFile("a"));
    // A file that the list leaves out has its own tab
    const unlisted = { ...file("c"), artifact_id: null, version: null };
    expect(openCardFileAction(unlisted, files)).toEqual({
      type: "openFile",
      file: unlisted,
      pinned: false,
    });
  });

  test("a shown file is seen", () => {
    const state = apply({ type: "markSeen", fileId: "a-v2" });
    expect(state.seenFileIds).toEqual(["a-v2"]);
    expect(rightPanelReducer(state, { type: "markSeen", fileId: "a-v2" })).toBe(
      state
    );
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

  test("showing Files after Sources restores the last Files tab", () => {
    let state = apply(openFile("a"), {
      type: "showTab",
      tabId: RIGHT_PANEL_FILES_TAB,
    });
    state = rightPanelReducer(state, {
      type: "showTab",
      tabId: RIGHT_PANEL_SOURCES_TAB,
    });
    state = rightPanelReducer(state, showFiles);
    expect(showsFiles(state)).toBe(true);
    expect(state.activeId).toBe(RIGHT_PANEL_FILES_TAB);
  });

  test("showing Files opens a chat without files on the Files list", () => {
    const state = apply(showFiles);
    expect(state.mode).toBe("medium");
    expect(state.activeId).toBe(RIGHT_PANEL_FILES_TAB);
  });

  test("hiding Sources closes the panel only when Sources is active", () => {
    const files = apply(showFiles);
    expect(rightPanelReducer(files, { type: "hideSources" })).toBe(files);

    const sources = apply({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
    expect(rightPanelReducer(sources, { type: "hideSources" }).mode).toBe(
      "closed"
    );
  });

  test("full size ends when the panel closes", () => {
    let state = apply(showFiles, { type: "setMode", mode: "full" });
    expect(state.mode).toBe("full");
    state = rightPanelReducer(state, { type: "closePanel" });
    state = rightPanelReducer(state, showFiles);
    expect(state.mode).toBe("medium");
  });
});
