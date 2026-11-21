/**
 * @jest-environment jsdom
 */
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { rightPanelFileTab } from "@/lib/chat/rightPanel";
import type { PublishedFile } from "@/app/app/services/streamingModels";

const FILE_A: PublishedFile = {
  file_id: "a",
  name: "a.md",
  title: null,
  path: "/w/a.md",
  display_path: "a.md",
  size: 1,
  mime_type: "text/markdown",
  artifact_id: "artifact-a",
  version: 1,
  thumbnail_file_id: null,
};

function panel(sessionId: string) {
  return useChatSessionStore.getState().sessions.get(sessionId)?.rightPanel;
}

function openChat(sessionId: string) {
  if (!useChatSessionStore.getState().sessions.has(sessionId))
    useChatSessionStore.getState().createSession(sessionId);
  useChatSessionStore.setState({ currentSessionId: sessionId });
}

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  window.sessionStorage.clear();
});

describe("the right panel, per chat", () => {
  test("each chat keeps its own tabs, search and seen files", () => {
    const store = useChatSessionStore.getState();
    openChat("first");
    store.updateCurrentRightPanel({
      type: "openFile",
      file: FILE_A,
      pinned: false,
    });
    store.updateCurrentRightPanel({
      type: "initializeSeen",
      fileIds: ["a", "b"],
    });
    store.updateCurrentRightPanel({ type: "setSearch", search: "report" });

    openChat("second");
    expect(panel("second")?.mode).toBe("closed");
    expect(panel("second")?.seenInitialized).toBe(false);
    store.updateCurrentRightPanel({ type: "showFiles" });

    openChat("first");
    expect(panel("first")).toMatchObject({
      mode: "medium",
      search: "report",
      seenFileIds: ["a", "b"],
    });
    expect(panel("first")?.activeId).toBe(rightPanelFileTab(FILE_A));
  });

  test("switching chats, then reopening the panel restores its tabs", () => {
    const store = useChatSessionStore.getState();
    openChat("first");
    store.updateCurrentRightPanel({
      type: "openFile",
      file: FILE_A,
      pinned: false,
    });
    store.updateCurrentRightPanel({ type: "closePanel" });
    openChat("second");
    openChat("first");

    store.updateCurrentRightPanel({ type: "showFiles" });
    expect(panel("first")?.activeId).toBe(rightPanelFileTab(FILE_A));
    expect(panel("first")?.mode).toBe("medium");
  });

  test("each chat keeps its panel width through a reload of the page", () => {
    openChat("first");
    useChatSessionStore
      .getState()
      .updateCurrentRightPanel({ type: "setProportion", proportion: 0.7 });
    openChat("second");
    expect(panel("second")?.proportion).toBe(0.5);

    // A reload starts with an empty store
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    openChat("first");
    expect(panel("first")?.proportion).toBe(0.7);
  });
});
