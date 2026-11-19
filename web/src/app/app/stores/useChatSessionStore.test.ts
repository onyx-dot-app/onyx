/**
 * @jest-environment jsdom
 */
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { rightPanelFileTab } from "@/lib/chat/rightPanel";
import { loadSelectedBranch } from "@/lib/chat/pagedSession";

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
    store.updateCurrentRightPanel({ type: "openFile", fileId: "a" });
    store.updateCurrentRightPanel({
      type: "initializeSeen",
      fileIds: ["a", "b"],
    });
    store.updateCurrentRightPanel({ type: "setSearch", search: "report" });

    openChat("second");
    expect(panel("second")?.mode).toBe("closed");
    expect(panel("second")?.seenInitialized).toBe(false);
    store.updateCurrentRightPanel({ type: "toggleFiles", shownFileTabs: [] });

    openChat("first");
    expect(panel("first")).toMatchObject({
      mode: "medium",
      search: "report",
      seenFileIds: ["a", "b"],
    });
    expect(panel("first")?.activeId).toBe(rightPanelFileTab("a"));
  });

  test("switching chats, then branches, then reopening the panel restores its tabs", async () => {
    const store = useChatSessionStore.getState();
    openChat("first");
    store.updateCurrentRightPanel({ type: "openFile", fileId: "a" });
    store.updateCurrentRightPanel({ type: "closePanel" });
    openChat("second");
    openChat("first");

    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ messages: [], packets: [], published_files: [] }),
          { status: 200 }
        )
      );
    try {
      await loadSelectedBranch(
        "first",
        Promise.resolve(new Response(null, { status: 200 })),
        false
      );
    } finally {
      jest.restoreAllMocks();
    }

    // File A is still on the branch
    store.updateCurrentRightPanel({
      type: "toggleFiles",
      shownFileTabs: [rightPanelFileTab("a")],
    });
    expect(panel("first")?.activeId).toBe(rightPanelFileTab("a"));
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
