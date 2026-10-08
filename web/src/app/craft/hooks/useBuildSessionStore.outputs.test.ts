import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchOutputInventory,
  fetchWebappInfo,
} from "@/app/craft/services/apiServices";
import type { OutputInventory } from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices", () => ({
  fetchOutputInventory: jest.fn(),
  fetchWebappInfo: jest.fn(),
}));

const sessionId = "output-session";
const store = () => useBuildSessionStore.getState();
const session = () => store().sessions.get(sessionId);
const oldFile = { path: "outputs/old.pdf", revision: "1:100", size: 100 };
const slides = {
  path: "outputs/slides/deck.pptx",
  revision: "2:200",
  size: 100,
};

async function refresh(files: OutputInventory["files"], complete = true) {
  jest.mocked(fetchOutputInventory).mockResolvedValue({ files, complete });
  await store().refreshOutputInventory(sessionId);
}

beforeEach(() => {
  jest.resetAllMocks();
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    noSessionOutputPanelOpen: false,
    noSessionActiveOutputTab: "files",
  });
  store().createSession(sessionId, { status: "running" });
  store().setCurrentSession(sessionId);
});

it("treats existing files as a silent baseline, including after a reload", async () => {
  await refresh([oldFile]);
  expect(session()).toMatchObject({
    outputPanelOpen: false,
    panelTabs: [],
    outputInventory: { [oldFile.path]: oldFile },
  });
  await refresh([oldFile, slides]);
  expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
  store().createSession(sessionId, { status: "active" });
  await refresh([oldFile, slides]);
  expect(session()).toMatchObject({ outputPanelOpen: false, panelTabs: [] });
});

it.each([false, true])(
  "selects a new file with panel open=%s",
  async (outputPanelOpen) => {
    await refresh([oldFile]);
    store().updateSessionData(sessionId, { outputPanelOpen });
    await refresh([oldFile, slides]);
    expect(session()).toMatchObject({
      outputPanelOpen: true,
      activePanelTabId: `file:${slides.path}`,
    });
  }
);

it("adds all previewable files but selects only one from a batch", async () => {
  await refresh([]);
  await refresh([
    { path: "outputs/notes.md", revision: "1", size: 100 },
    slides,
    oldFile,
  ]);
  expect(session()?.panelTabs).toHaveLength(3);
  expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
  expect(session()?.tabHistory.entries).toHaveLength(2);
});

it.each([false, true])(
  "keeps the first automatic selection when later files arrive with panel open=%s",
  async (outputPanelOpen) => {
    await refresh([]);
    store().updateSessionData(sessionId, { outputPanelOpen });
    await refresh([oldFile]);
    expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);

    // A later, higher-priority presentation must not replace the visible PDF.
    await refresh([oldFile, slides]);
    expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
    expect(session()?.panelTabs).toHaveLength(2);
    expect(session()?.tabHistory.entries).toHaveLength(2);

    await refresh([{ ...oldFile, revision: "3:100", size: 100 }, slides]);
    expect(session()).toMatchObject({
      activePanelTabId: `file:${oldFile.path}`,
      outputInventory: { [oldFile.path]: { ...oldFile, revision: "3:100" } },
    });
    store().setActivePanelTabId(sessionId, `file:${slides.path}`);
    expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
  }
);

it("refreshes an updated file without changing the selected tab", async () => {
  await refresh([oldFile, slides]);
  store().openFilePreview(sessionId, oldFile.path, "old.pdf");
  await refresh([{ ...oldFile, revision: "3:100", size: 100 }, slides]);
  expect(session()).toMatchObject({
    activePanelTabId: `file:${oldFile.path}`,
    outputInventory: { [oldFile.path]: { ...oldFile, revision: "3:100" } },
  });
  await refresh([{ ...oldFile, revision: "3:100", size: 100 }, slides]);
  expect(session()?.outputInventory?.[oldFile.path]?.revision).toBe("3:100");
});

it("does not reopen a closed file tab when its content changes", async () => {
  await refresh([oldFile]);
  store().openFilePreview(sessionId, oldFile.path, "old.pdf");
  store().closePanelTab(sessionId, `file:${oldFile.path}`);
  await refresh([{ ...oldFile, revision: "2:100", size: 100 }]);
  expect(session()).toMatchObject({ activePanelTabId: null, panelTabs: [] });
});

it("adds a new tab without overriding a manual selection", async () => {
  await refresh([oldFile]);
  store().openFilePreview(sessionId, oldFile.path, "old.pdf");
  await refresh([oldFile, slides]);
  expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
  expect(session()?.panelTabs).toHaveLength(2);
});

it("honors manual dismissal even when a request was already in flight", async () => {
  await refresh([]);
  jest.mocked(fetchOutputInventory).mockImplementationOnce(async () => {
    store().toggleCurrentOutputPanel();
    store().toggleCurrentOutputPanel();
    return { files: [slides], complete: true };
  });
  await store().refreshOutputInventory(sessionId);
  expect(session()).toMatchObject({
    outputPanelOpen: false,
    panelManuallyDismissed: true,
    activePanelTabId: null,
  });
});

it.each(["make_slides.py", "report.xlsx"])(
  "does not open a generic panel for %s",
  async (fileName) => {
    await refresh([]);
    await refresh([{ path: `outputs/${fileName}`, revision: "1", size: 100 }]);
    expect(session()).toMatchObject({
      outputPanelOpen: false,
      activePanelTabId: null,
    });
  }
);

it("opens directly on the slide deck after its helper script appears", async () => {
  await refresh([]);
  const helper = { path: "outputs/make_slides.py", revision: "1", size: 100 };
  const openedTargets: Array<string | null> = [];
  const unsubscribe = useBuildSessionStore.subscribe((state) => {
    const current = state.sessions.get(sessionId);
    if (current?.outputPanelOpen) openedTargets.push(current.activePanelTabId);
  });
  try {
    await refresh([helper]);
    expect(openedTargets).toEqual([]);
    await refresh([helper, slides]);
    expect(openedTargets).toEqual([`file:${slides.path}`]);
  } finally {
    unsubscribe();
  }
});

it("does not open Preview or its Files fallback when no webapp exists", async () => {
  jest.mocked(fetchWebappInfo).mockResolvedValue({
    has_webapp: false,
    ready: false,
    webapp_url: null,
    status: "running",
    sharing_scope: "private",
  });
  await store().maybeAutoOpenWebapp(sessionId);
  expect(session()?.outputPanelOpen).toBe(false);
});

it("shares readiness checks and opens Preview only once the webapp serves", async () => {
  jest.useFakeTimers();
  try {
    const webapp = {
      has_webapp: true,
      ready: false,
      webapp_url: "/webapp",
      status: "running",
      sharing_scope: "private" as const,
    };
    jest
      .mocked(fetchWebappInfo)
      .mockResolvedValueOnce(webapp)
      .mockResolvedValue({ ...webapp, ready: true });
    const first = store().maybeAutoOpenWebapp(sessionId);
    const second = store().maybeAutoOpenWebapp(sessionId);
    await jest.advanceTimersByTimeAsync(0);
    expect(fetchWebappInfo).toHaveBeenCalledTimes(1);
    expect(session()?.outputPanelOpen).toBe(false);
    await jest.advanceTimersByTimeAsync(1500);
    await Promise.all([first, second]);
    expect(session()).toMatchObject({
      outputPanelOpen: true,
      activeOutputTab: "preview",
    });
    expect(fetchWebappInfo).toHaveBeenCalledTimes(2);
  } finally {
    jest.useRealTimers();
  }
});

it("releases a stalled readiness check so a later task can retry", async () => {
  jest.useFakeTimers();
  try {
    let requestSignal: AbortSignal | undefined;
    jest.mocked(fetchWebappInfo).mockImplementationOnce((_id, signal) => {
      requestSignal = signal;
      return new Promise((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true }
        );
      });
    });
    const first: Promise<void> = store().maybeAutoOpenWebapp(sessionId);
    const shared: Promise<void> = store().maybeAutoOpenWebapp(sessionId);
    await jest.advanceTimersByTimeAsync(30000);
    expect(requestSignal?.aborted).toBe(true);
    await Promise.all([first, shared]);
    expect(fetchWebappInfo).toHaveBeenCalledTimes(1);
    expect(session()?.outputPanelOpen).toBe(false);
    store().updateSessionData(sessionId, { turnGeneration: 1 });
    jest.mocked(fetchWebappInfo).mockResolvedValue({
      has_webapp: true,
      ready: true,
      webapp_url: "/webapp",
      status: "running",
      sharing_scope: "private",
    });
    await store().maybeAutoOpenWebapp(sessionId);
    expect(fetchWebappInfo).toHaveBeenCalledTimes(2);
    expect(session()).toMatchObject({
      outputPanelOpen: true,
      activeOutputTab: "preview",
    });
  } finally {
    jest.useRealTimers();
  }
});

it.each(["file", "dismissal", "new turn"] as const)(
  "does not let a late webapp check override %s",
  async (change) => {
    let resolveReady:
      | ((info: Awaited<ReturnType<typeof fetchWebappInfo>>) => void)
      | undefined;
    jest.mocked(fetchWebappInfo).mockReturnValue(
      new Promise((resolve) => {
        resolveReady = resolve;
      })
    );
    const pending = store().maybeAutoOpenWebapp(sessionId);
    if (change === "file") {
      await refresh([]);
      await refresh([slides]);
    } else if (change === "dismissal") {
      store().toggleCurrentOutputPanel();
      store().toggleCurrentOutputPanel();
    } else {
      store().updateSessionData(sessionId, { turnGeneration: 1 });
    }
    resolveReady?.({
      has_webapp: true,
      ready: true,
      webapp_url: "/webapp",
      status: "running",
      sharing_scope: "private",
    });
    await pending;
    expect(session()).toMatchObject(
      change === "file"
        ? { outputPanelOpen: true, activePanelTabId: `file:${slides.path}` }
        : { outputPanelOpen: false, activePanelTabId: null }
    );
  }
);

it("does not treat missing entries in a partial response as deletions", async () => {
  await refresh([oldFile, slides]);
  await refresh([slides], false);
  expect(session()?.outputInventory).toHaveProperty([oldFile.path], oldFile);
  expect(session()?.filesNeedsRefresh).toBe(0);
  await refresh([slides]);
  expect(session()?.outputInventory?.[oldFile.path]).toBeUndefined();
  expect(session()?.filesNeedsRefresh).toBe(1);
});

it("waits for a complete baseline instead of revealing old files after a partial read", async () => {
  await refresh([oldFile], false);
  expect(session()?.outputInventory).toEqual({ [oldFile.path]: oldFile });
  expect(session()?.outputInventoryStatus).toBe("partial");
  expect(session()?.outputBaselinePending).toBe(true);
  await refresh([oldFile, slides]);
  expect(session()).toMatchObject({ outputPanelOpen: false, panelTabs: [] });
});

it("discards a delayed response from an older turn", async () => {
  await refresh([]);
  jest.mocked(fetchOutputInventory).mockImplementationOnce(async () => {
    store().updateSessionData(sessionId, { turnGeneration: 1 });
    return { files: [slides], complete: true };
  });
  await store().refreshOutputInventory(sessionId);
  expect(session()).toMatchObject({
    outputPanelOpen: false,
    outputInventory: {},
  });
});

it("finishes turn discovery before an idle focus refresh can consume its files", async () => {
  await refresh([]);
  store().updateSessionData(sessionId, { activeTurnId: "finishing-turn" });
  let resolveDiscovery: ((inventory: OutputInventory) => void) | undefined;
  jest.mocked(fetchOutputInventory).mockReturnValueOnce(
    new Promise((resolve) => {
      resolveDiscovery = resolve;
    })
  );
  const discovery = store().refreshOutputInventory(sessionId);
  // prompt_response settles the transcript while the final inventory is pending.
  store().updateSessionData(sessionId, {
    status: "active",
    activeTurnId: null,
  });
  jest
    .mocked(fetchOutputInventory)
    .mockResolvedValue({ files: [slides], complete: true });
  const focus = store().refreshOutputInventory(sessionId, { silent: true });
  expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
  resolveDiscovery?.({ files: [slides], complete: true });
  await Promise.all([discovery, focus]);
  expect(fetchOutputInventory).toHaveBeenCalledTimes(3);
  expect(session()).toMatchObject({
    outputPanelOpen: true,
    activePanelTabId: `file:${slides.path}`,
    outputInventory: { [slides.path]: slides },
  });
});

it.each(["aborted", "superseded"] as const)(
  "skips a queued inventory read when its turn is %s",
  async (reason) => {
    await refresh([]);
    let finishFirst: ((inventory: OutputInventory) => void) | undefined;
    jest.mocked(fetchOutputInventory).mockReturnValueOnce(
      new Promise((resolve) => {
        finishFirst = resolve;
      })
    );
    const first = store().refreshOutputInventory(sessionId);
    const controller = new AbortController();
    const queued = store().refreshOutputInventory(sessionId, {
      signal: controller.signal,
    });
    if (reason === "aborted") controller.abort();
    else store().updateSessionData(sessionId, { turnGeneration: 1 });
    finishFirst?.({ files: [], complete: true });
    await Promise.all([first, queued]);
    expect(fetchOutputInventory).toHaveBeenCalledTimes(2);

    // The queue must release after either skipped request.
    await refresh([slides]);
    expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
  }
);

it("discards a silent response when a turn attaches before it completes", async () => {
  await refresh([]);
  let resolveSilent: ((inventory: OutputInventory) => void) | undefined;
  jest.mocked(fetchOutputInventory).mockReturnValueOnce(
    new Promise((resolve) => {
      resolveSilent = resolve;
    })
  );
  const silent = store().refreshOutputInventory(sessionId, { silent: true });
  store().updateSessionData(sessionId, { activeTurnId: "attached-turn" });
  resolveSilent?.({ files: [slides], complete: true });
  await silent;
  expect(session()?.outputInventory).toEqual({});
  await refresh([slides]);
  expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
});

it("applies successive silent refreshes without selecting existing files", async () => {
  let resolveFirst: ((inventory: OutputInventory) => void) | undefined;
  let resolveSecond: ((inventory: OutputInventory) => void) | undefined;
  jest
    .mocked(fetchOutputInventory)
    .mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFirst = resolve;
      })
    )
    .mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSecond = resolve;
      })
    );
  const first = store().refreshOutputInventory(sessionId, { silent: true });
  const second = store().refreshOutputInventory(sessionId, { silent: true });
  resolveFirst?.({ files: [oldFile], complete: true });
  await first;
  expect(session()?.outputInventory).toEqual({
    [oldFile.path]: oldFile,
  });
  resolveSecond?.({ files: [oldFile, slides], complete: true });
  await second;
  await refresh([oldFile, slides]);
  expect(session()?.activePanelTabId).toBeNull();
  expect(session()?.outputInventory).toEqual({
    [oldFile.path]: oldFile,
    [slides.path]: slides,
  });
});

it("keeps another session's output and selection isolated", async () => {
  await refresh([]);
  store().setCurrentSession("other-session");
  await refresh([slides]);
  expect(store().currentSessionId).toBe("other-session");
  expect(store().sessions.get("other-session")).toMatchObject({
    outputInventory: null,
    outputPanelOpen: false,
  });
  expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
});

it("preserves the baseline on a failed read", async () => {
  const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
  await refresh([oldFile]);
  jest
    .mocked(fetchOutputInventory)
    .mockRejectedValueOnce(new Error("sandbox unavailable"));
  await store().refreshOutputInventory(sessionId);
  expect(session()?.outputInventory).toEqual({
    [oldFile.path]: oldFile,
  });
  expect(session()?.status).toBe("running");
  warn.mockRestore();
});

it("allows new-file selection after a dismissed panel has been reopened", async () => {
  await refresh([]);
  store().updateSessionData(sessionId, {
    outputPanelOpen: true,
    panelManuallyDismissed: true,
    outputSelectionLocked: false,
  });
  await refresh([slides]);
  expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
});

it.each([
  ["a pinned tab click", () => store().setActiveOutputTab(sessionId, "files")],
  [
    "a file tab click",
    () => store().setActivePanelTabId(sessionId, `file:${oldFile.path}`),
  ],
  [
    "closing a panel tab",
    () => store().closePanelTab(sessionId, `file:${slides.path}`),
  ],
  ["back navigation", () => store().navigateTabBack(sessionId)],
  [
    "forward navigation",
    () => {
      store().updateSessionData(sessionId, {
        tabHistory: { entries: session()!.tabHistory.entries, currentIndex: 0 },
      });
      store().navigateTabForward(sessionId);
    },
  ],
])("preserves the user's selection after %s", async (_label, navigate) => {
  await refresh([]);
  await refresh([oldFile, slides]);
  // A new task permits selection again, until the user navigates.
  store().updateSessionData(sessionId, { outputSelectionLocked: false });
  expect(session()?.outputSelectionLocked).toBe(false);

  navigate();
  const selected = {
    activeOutputTab: session()?.activeOutputTab,
    activePanelTabId: session()?.activePanelTabId,
  };
  expect(session()?.outputSelectionLocked).toBe(true);

  const newFile = { path: "outputs/new.pdf", revision: "3:100", size: 100 };
  await refresh([oldFile, slides, newFile]);
  expect(session()).toMatchObject(selected);
  expect(session()?.panelTabs).toContainEqual({
    kind: "file",
    path: newFile.path,
    fileName: "new.pdf",
  });
});

it("reopens closed file tabs through history without adding history entries", async () => {
  await refresh([]);
  await refresh([oldFile]);
  await refresh([oldFile, slides]);
  store().setActivePanelTabId(sessionId, `file:${slides.path}`);
  store().closePanelTab(sessionId, `file:${oldFile.path}`);
  store().navigateTabBack(sessionId);
  expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
  expect(session()?.panelTabs).toContainEqual({
    kind: "file",
    path: oldFile.path,
    fileName: "old.pdf",
  });
  store().navigateTabForward(sessionId);
  expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
  expect(session()?.tabHistory.entries).toHaveLength(3);
});

it.each([false, true])(
  "locks an automatic webapp selection when the panel was open=%s",
  async (outputPanelOpen) => {
    await refresh([]);
    store().updateSessionData(sessionId, {
      outputPanelOpen,
      activeOutputTab: "files",
    });
    jest.mocked(fetchWebappInfo).mockResolvedValue({
      has_webapp: true,
      ready: true,
      webapp_url: "/webapp",
      status: "running",
      sharing_scope: "private",
    });
    await store().maybeAutoOpenWebapp(sessionId);
    expect(session()).toMatchObject({
      outputPanelOpen: true,
      activeOutputTab: "preview",
      outputSelectionLocked: true,
    });
    await refresh([slides]);
    expect(session()).toMatchObject({
      activeOutputTab: "preview",
      activePanelTabId: null,
    });
    expect(session()?.panelTabs).toHaveLength(1);
  }
);

it.each(["stop", "manual selection"])(
  "does not select a webapp that becomes ready after %s",
  async (action) => {
    store().updateSessionData(sessionId, {
      outputPanelOpen: true,
      activeOutputTab: "files",
    });
    let resolveReady:
      | ((value: Awaited<ReturnType<typeof fetchWebappInfo>>) => void)
      | undefined;
    jest.mocked(fetchWebappInfo).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveReady = resolve;
      })
    );
    const pending = store().maybeAutoOpenWebapp(sessionId);
    if (action === "stop")
      store().updateSessionData(sessionId, { wasInterrupted: true });
    else store().setActiveOutputTab(sessionId, "files");
    resolveReady?.({
      has_webapp: true,
      ready: true,
      webapp_url: "/webapp",
      status: "running",
      sharing_scope: "private",
    });
    await pending;
    expect(session()).toMatchObject({
      activeOutputTab: "files",
      activePanelTabId: null,
    });
  }
);

it.each([true, false])(
  "reconciles file/folder replacement during a partial scan (directory=%s)",
  async (directory) => {
    const parent = { path: "outputs/report", revision: "1", size: 100 };
    const child = {
      path: "outputs/report/slides.pdf",
      revision: "2",
      size: 100,
    };
    await refresh([directory ? parent : child]);
    await refresh([directory ? child : parent], false);
    expect(session()?.outputInventory).toEqual(
      directory ? { [child.path]: child } : { [parent.path]: parent }
    );
  }
);
