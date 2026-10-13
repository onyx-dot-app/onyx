/** @jest-environment jsdom */
import { act, deferred, renderHook, waitFor } from "@tests/setup/test-utils";
import {
  useBuildSessionStore,
  useOutputWorkspaceId,
  useChatSession,
  useOutputSession,
  waitForWebappReady,
} from "@/app/craft/hooks/useBuildSessionStore";
import { FetchError } from "@/lib/fetcher";
import * as api from "@/app/craft/services/apiServices";
import {
  fetchOutputInventory,
  fetchWebappInfo,
  deleteSession,
  fetchSessionHistory,
} from "@/app/craft/services/apiServices";
import * as panelPreferences from "@/app/craft/services/outputPanelPreferences";
import type {
  OutputInventory,
  ApiDetailedSessionResponse,
  BuildMessageAttachment,
} from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices");

const initialState = useBuildSessionStore.getState();
beforeEach(() => {
  jest.resetAllMocks();
  sessionStorage.clear();
  useBuildSessionStore.setState(initialState, true);
  useBuildSessionStore.getState().setCurrentSession(null);
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

// --- Welcome workspace handoff ---
describe("Welcome workspace handoff", () => {
  const store = () => useBuildSessionStore.getState();

  it("preserves the open welcome panel when creating a conversation", () => {
    store().setCurrentSession(null);
    store().toggleCurrentOutputPanel();
    expect(store().noSessionActivePanelTabId).toBe("outputs");

    const workspaceId = store().noSessionOutputWorkspaceId;
    const newSessionId = "from-welcome";
    store().createSession(newSessionId);
    store().setCurrentSession(newSessionId);

    expect(store().sessions.get(newSessionId)).toMatchObject({
      outputWorkspaceId: workspaceId,
      outputPanelMode: "medium",
      panelTabs: [{ kind: "outputs" }],
      activePanelTabId: "outputs",
    });
  });

  it("starts a saved session with no selected output resource", () => {
    store().setCurrentSession(null);
    store().setCurrentSession("saved-session");
    expect(store().sessions.get("saved-session")).toMatchObject({
      panelTabs: [],
      activePanelTabId: null,
    });
  });

  it("honors explicit initial resources instead of the welcome selection", () => {
    store().setCurrentSession(null);
    const tab = {
      kind: "browser" as const,
      id: "app-tab",
      appId: "explicit-app",
    };
    store().createSession("explicit-app", {
      panelTabs: [tab],
      activePanelTabId: "browser:app-tab",
    });
    expect(store().sessions.get("explicit-app")).toMatchObject({
      panelTabs: [tab],
      activePanelTabId: "browser:app-tab",
    });
  });

  it("keeps the welcome workspace identity while provisioning and claiming its session", () => {
    store().createSession("pre-provisioned");
    store().setCurrentSession(null);
    store().openFilesTab(null);
    const workspaceId = store().noSessionOutputWorkspaceId;
    const { result } = renderHook(useOutputWorkspaceId);
    expect(result.current).toBe(workspaceId);
    act(() =>
      useBuildSessionStore.setState({
        preProvisioning: { status: "ready", sessionId: "pre-provisioned" },
      })
    );
    expect(result.current).toBe(workspaceId);
    expect(store().sessions.get("pre-provisioned")?.outputWorkspaceId).toBe(
      "pre-provisioned"
    );
    act(() => store().setCurrentSession("pre-provisioned"));
    expect(result.current).toBe(workspaceId);
    expect(store().sessions.get("pre-provisioned")?.outputWorkspaceId).toBe(
      workspaceId
    );
  });

  it("changes workspace identity for another session and a new welcome workspace", () => {
    store().setCurrentSession(null);
    store().openFilesTab(null);
    const welcomeId = store().noSessionOutputWorkspaceId;
    store().createSession("claimed");
    store().setCurrentSession("claimed");
    const { result } = renderHook(useOutputWorkspaceId);
    expect(result.current).toBe(welcomeId);
    act(() => {
      store().createSession("unrelated");
      store().setCurrentSession("unrelated");
    });
    expect(result.current).toBe("unrelated");
    expect(store().sessions.get("unrelated")?.panelTabs).toEqual([]);
    act(() => store().setCurrentSession(null));
    expect(result.current).not.toBe(welcomeId);
    expect(result.current).not.toBe("unrelated");
  });
});

// --- Output resources and inventory ---
describe("Output resources and inventory", () => {
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
    await store().refreshOutputInventory(sessionId, { silent: true });
  }

  beforeEach(() => {
    store().createSession(sessionId, { status: "running" });
    store().setCurrentSession(sessionId);
  });

  it("starts closed and opens Outputs at an equal split", () => {
    expect(session()).toMatchObject({
      outputPanelMode: "closed",
      mediumPanelProportion: 0.5,
      panelTabs: [],
    });
    store().toggleCurrentOutputPanel();
    expect(session()).toMatchObject({
      outputPanelMode: "medium",
      panelTabs: [{ kind: "outputs" }],
      activePanelTabId: "outputs",
    });
  });

  it("restores the split and resources after closing full", () => {
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().setCurrentMediumPanelProportion(0.63);
    store().setCurrentOutputPanelMode("full");
    store().toggleCurrentOutputPanel();
    expect(session()?.outputPanelMode).toBe("closed");
    store().toggleCurrentOutputPanel();
    expect(session()).toMatchObject({
      outputPanelMode: "medium",
      mediumPanelProportion: 0.63,
      activePanelTabId: `file:${oldFile.path}`,
    });
  });

  it.each(["closed", "medium", "full"] as const)(
    "explicit file opening from %s retains the correct mode",
    (mode) => {
      store().setCurrentOutputPanelMode(mode);
      store().openFilePreview(sessionId, oldFile.path, "old.pdf");
      expect(session()?.outputPanelMode).toBe(
        mode === "closed" ? "medium" : mode
      );
    }
  );

  it("normalizes file identity and keeps duplicate basenames distinct", () => {
    store().openFilePreview(sessionId, "outputs/./old.pdf", "old.pdf");
    store().openFilePreview(sessionId, "outputs/old.pdf", "old.pdf");
    store().openFilePreview(sessionId, "attachments/old.pdf", "old.pdf");
    expect(session()?.panelTabs).toHaveLength(2);
    expect(session()?.activePanelTabId).toBe("file:attachments/old.pdf");
  });

  it("preserves literal backslashes as distinct Linux filenames", () => {
    const literal = String.raw`outputs/report\final.txt`;
    store().openFilePreview(sessionId, literal, String.raw`report\final.txt`);
    store().openFilePreview(sessionId, "outputs/report/final.txt", "final.txt");
    expect(session()?.panelTabs).toEqual([
      { kind: "file", path: literal, fileName: String.raw`report\final.txt` },
      { kind: "file", path: "outputs/report/final.txt", fileName: "final.txt" },
    ]);
    store().openFilePreview(sessionId, literal, String.raw`report\final.txt`);
    expect(session()?.activePanelTabId).toBe(`file:${literal}`);
    expect(session()?.panelTabs).toHaveLength(2);
  });

  it("keeps Files unique and recreates it after closing", () => {
    store().openFilesTab(sessionId);
    store().openFilesTab(sessionId);
    expect(session()?.panelTabs).toEqual([{ kind: "files" }]);
    store().closePanelTab(sessionId, "files");
    expect(session()).toMatchObject({
      panelTabs: [],
      activePanelTabId: null,
      outputPanelMode: "medium",
    });
    store().openFilesTab(sessionId);
    expect(session()?.panelTabs).toEqual([{ kind: "files" }]);
  });

  it("returns to a viewed tab and leaves inactive selection unchanged", () => {
    store().openFilesTab(sessionId);
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().openFilePreview(sessionId, slides.path, "deck.pptx");
    store().closePanelTab(sessionId, "files");
    expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
    store().closePanelTab(sessionId, `file:${slides.path}`);
    expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
    store().closePanelTab(sessionId, `file:${oldFile.path}`);
    store().toggleCurrentOutputPanel();
    store().toggleCurrentOutputPanel();
    expect(session()).toMatchObject({
      panelTabs: [],
      activePanelTabId: null,
      outputPanelMode: "medium",
    });
  });

  it("returns through viewing history regardless of tab order without mutating previous state", () => {
    store().openOutputsTab(sessionId);
    store().openFilesTab(sessionId);
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().setActivePanelTabId(sessionId, "outputs");
    store().setActivePanelTabId(sessionId, `file:${oldFile.path}`);
    store().setActivePanelTabId(sessionId, `file:${oldFile.path}`);
    const previous = session();
    store().reorderPanelTab(sessionId, "files", 2);
    store().closePanelTab(sessionId, `file:${oldFile.path}`);
    expect(session()?.activePanelTabId).toBe("outputs");
    expect(previous?.panelTabHistory).toEqual([
      `file:${oldFile.path}`,
      "outputs",
      "files",
    ]);
    store().closePanelTab(sessionId, "outputs");
    expect(session()?.activePanelTabId).toBe("files");
    store().closePanelTab(sessionId, "files");
    expect(session()?.panelTabHistory).toEqual([]);
    store().openFilesTab(sessionId);
    expect(session()?.panelTabHistory).toEqual(["files"]);
  });

  it("restores viewing history after reload and prunes stale or duplicate entries", () => {
    store().openOutputsTab(sessionId);
    store().openFilesTab(sessionId);
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().setActivePanelTabId(sessionId, "outputs");
    const saved = session();
    if (!saved) throw new Error("Missing session");
    panelPreferences.saveOutputPanelPreferences(sessionId, {
      ...saved,
      panelTabHistory: [...saved.panelTabHistory, "missing", "outputs"],
    });
    store().createSession(sessionId);
    store().closePanelTab(sessionId, "outputs");
    expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
    expect(session()?.panelTabHistory).toEqual([
      `file:${oldFile.path}`,
      "files",
    ]);
  });

  it("keeps history session-local and transfers welcome history when claimed", () => {
    store().openFilesTab(sessionId);
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().setCurrentSession(null);
    store().openFilesTab(null);
    store().openOutputsTab(null);
    store().openFilePreview(null, slides.path, "deck.pptx");
    store().setActivePanelTabId(null, "files");
    store().closePanelTab(null, "files");
    expect(store().noSessionActivePanelTabId).toBe(`file:${slides.path}`);
    store().createSession("claimed");
    store().setCurrentSession("claimed");
    store().closePanelTab("claimed", `file:${slides.path}`);
    expect(store().sessions.get("claimed")?.activePanelTabId).toBe("outputs");
    store().setCurrentSession(sessionId);
    store().closePanelTab(sessionId, `file:${oldFile.path}`);
    expect(session()?.activePanelTabId).toBe("files");
  });

  it("selects the first remaining tab when closing the first active tab", () => {
    store().openFilesTab(sessionId);
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().setActivePanelTabId(sessionId, "files");
    store().closePanelTab(sessionId, "files");
    expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
  });

  it("keeps Browser identity stable through navigation and deduplicates app output opens", () => {
    store().openBrowserTab(sessionId);
    const firstId = session()?.activePanelTabId;
    store().openBrowserTab(sessionId);
    const secondId = session()?.activePanelTabId;
    expect(secondId).not.toBe(firstId);
    if (!firstId) throw new Error("Browser tab missing");
    store().navigateBrowserTab(sessionId, firstId, sessionId, "My app");
    store().openBrowserTab(sessionId, sessionId, "My app");
    expect(session()?.panelTabs).toHaveLength(2);
    expect(session()?.activePanelTabId).toBe(firstId);
    store().navigateBrowserTab(sessionId, firstId, null);
    expect(session()?.panelTabs[0]).toMatchObject({
      kind: "browser",
      appId: null,
    });
    expect(session()?.panelTabs[1]).toMatchObject({
      kind: "browser",
      appId: null,
    });
  });

  it("reorders resources without replacing their content identity or selection", () => {
    store().openFilesTab(sessionId);
    store().openBrowserTab(sessionId);
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    const original = session()?.panelTabs;
    store().reorderPanelTab(sessionId, `file:${oldFile.path}`, 0);
    expect(session()?.panelTabs).toEqual([
      original?.[2],
      original?.[0],
      original?.[1],
    ]);
    expect(session()?.panelTabs[0]).toBe(original?.[2]);
    expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
  });

  it("never creates tabs or opens the panel from passive file or app discoveries", async () => {
    await refresh([]);
    await refresh([oldFile, slides]);
    expect(fetchWebappInfo).not.toHaveBeenCalled();
    expect(session()).toMatchObject({
      outputPanelMode: "closed",
      panelTabs: [],
      activePanelTabId: null,
    });
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().setCurrentOutputPanelMode("full");
    await refresh([
      oldFile,
      slides,
      { path: "outputs/new.md", revision: "1", size: 1 },
    ]);
    expect(session()).toMatchObject({
      outputPanelMode: "full",
      activePanelTabId: `file:${oldFile.path}`,
    });
    expect(session()?.panelTabs).toHaveLength(1);
  });

  it("retains cached outputs while a pending refresh settles", async () => {
    await refresh([oldFile]);
    let finishRead: ((inventory: OutputInventory) => void) | undefined;
    jest.mocked(fetchOutputInventory).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishRead = resolve;
        })
    );
    const request = store().refreshOutputInventory(sessionId, { silent: true });
    expect(session()).toMatchObject({
      outputInventoryStatus: "complete",
      outputInventoryLoading: true,
      outputInventory: { [oldFile.path]: oldFile },
    });
    finishRead?.({ files: [oldFile], complete: false });
    await request;
    expect(session()?.outputInventoryStatus).toBe("partial");
    await refresh([oldFile]);
    expect(session()?.outputInventoryStatus).toBe("complete");
  });

  it("clears request loading after cancellation without losing accepted completeness", async () => {
    await refresh([oldFile]);
    const cancelled = deferred<OutputInventory>();
    jest.mocked(fetchOutputInventory).mockReturnValueOnce(cancelled.promise);
    const controller = new AbortController();
    const request = store().refreshOutputInventory(sessionId, {
      silent: true,
      signal: controller.signal,
    });
    controller.abort();
    cancelled.resolve({ files: [], complete: true });
    await request;
    expect(session()).toMatchObject({
      outputInventoryStatus: "complete",
      outputInventoryLoading: false,
      outputInventory: { [oldFile.path]: oldFile },
    });
  });

  it("keeps loading owned by a newer queued read when an earlier read is cancelled", async () => {
    await refresh([oldFile]);
    const previous = deferred<OutputInventory>();
    const current = deferred<OutputInventory>();
    jest
      .mocked(fetchOutputInventory)
      .mockReturnValueOnce(previous.promise)
      .mockReturnValueOnce(current.promise);
    const controller = new AbortController();
    const first = store().refreshOutputInventory(sessionId, {
      signal: controller.signal,
    });
    const second = store().refreshOutputInventory(sessionId);
    controller.abort();
    previous.resolve({ files: [], complete: true });
    await first;
    expect(session()?.outputInventoryLoading).toBe(true);
    current.resolve({ files: [oldFile], complete: true });
    await second;
    expect(session()?.outputInventoryLoading).toBe(false);
    expect(session()?.outputInventoryStatus).toBe("complete");
  });

  it("opens new previewable outputs once per task in priority order", async () => {
    await refresh([oldFile]);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      files: [
        oldFile,
        { path: "outputs/readme.md", revision: "1", size: 1 },
        slides,
      ],
      complete: true,
    });
    await store().refreshOutputInventory(sessionId);
    expect(session()).toMatchObject({
      outputPanelMode: "medium",
      activePanelTabId: `file:${slides.path}`,
      outputSelectionLocked: true,
    });
    expect(
      session()?.panelTabs.map((tab) =>
        tab.kind === "file" ? tab.path : tab.kind
      )
    ).toEqual(["outputs", slides.path, "outputs/readme.md"]);
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      files: [
        oldFile,
        slides,
        { path: "outputs/next.pdf", revision: "1", size: 1 },
      ],
      complete: true,
    });
    await store().refreshOutputInventory(sessionId);
    expect(session()?.activePanelTabId).toBe(`file:${slides.path}`);
  });

  it("preserves manual selection and dismissal while adding new output tabs", async () => {
    await refresh([]);
    store().openOutputsTab(sessionId);
    jest
      .mocked(fetchOutputInventory)
      .mockResolvedValue({ files: [slides], complete: true });
    await store().refreshOutputInventory(sessionId);
    expect(session()?.activePanelTabId).toBe("outputs");
    store().setCurrentOutputPanelMode("closed");
    jest
      .mocked(fetchOutputInventory)
      .mockResolvedValue({ files: [slides, oldFile], complete: true });
    await store().refreshOutputInventory(sessionId);
    expect(session()?.outputPanelMode).toBe("closed");
  });

  it("never attributes an incomplete baseline or passive discovery to the task", async () => {
    jest
      .mocked(fetchOutputInventory)
      .mockResolvedValue({ files: [], complete: false });
    await store().refreshOutputInventory(sessionId);
    jest
      .mocked(fetchOutputInventory)
      .mockResolvedValue({ files: [slides], complete: true });
    await store().refreshOutputInventory(sessionId);
    expect(session()?.panelTabs).toEqual([]);
    expect(session()?.outputBaselinePending).toBe(false);
  });

  it("keeps Outputs unique and preserves explicit empty panels", () => {
    store().openOutputsTab(sessionId);
    store().openOutputsTab(sessionId);
    expect(session()?.panelTabs).toEqual([{ kind: "outputs" }]);
    store().closePanelTab(sessionId, "outputs");
    store().toggleCurrentOutputPanel();
    store().toggleCurrentOutputPanel();
    expect(session()?.panelTabs).toEqual([]);
  });

  it("preserves a missing file tab after an authoritative inventory removes its file", async () => {
    await refresh([oldFile]);
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    await refresh([]);
    expect(session()?.outputInventory).toEqual({});
    expect(session()?.activePanelTabId).toBe(`file:${oldFile.path}`);
    expect(session()?.panelTabs).toHaveLength(1);
  });

  it("supports a no-session panel without creating a session and retains an empty workspace", () => {
    store().setCurrentSession(null);
    store().toggleCurrentOutputPanel();
    expect(store().noSessionPanelTabs).toEqual([{ kind: "outputs" }]);
    store().openBrowserTab(null);
    const browserId = store().noSessionActivePanelTabId;
    store().closePanelTab(null, "outputs");
    if (!browserId) throw new Error("Browser tab missing");
    store().closePanelTab(null, browserId);
    store().toggleCurrentOutputPanel();
    store().toggleCurrentOutputPanel();
    expect(store().noSessionPanelTabs).toEqual([]);
    expect(store().currentSessionId).toBeNull();
  });

  it("carries no-session tabs, selection, and split into the newly claimed session", () => {
    store().setCurrentSession(null);
    store().toggleCurrentOutputPanel();
    store().openBrowserTab(null);
    store().setCurrentMediumPanelProportion(0.6);
    const tabs = store().noSessionPanelTabs;
    const active = store().noSessionActivePanelTabId;
    store().createSession("claimed-session");
    store().setCurrentSession("claimed-session");
    expect(store().sessions.get("claimed-session")).toMatchObject({
      panelTabs: tabs,
      activePanelTabId: active,
      mediumPanelProportion: 0.6,
      outputPanelMode: "medium",
    });
  });

  it("transfers welcome file tabs when claiming an already-created pre-provisioned session", () => {
    store().setCurrentSession(null);
    useBuildSessionStore.setState({
      preProvisioning: { status: "starting", sessionId },
    });
    store().openFilePreview(null, "outputs/notes.txt", "notes.txt");
    store().setCurrentSession(sessionId);
    expect(session()).toMatchObject({
      outputPanelMode: "medium",
      activePanelTabId: "file:outputs/notes.txt",
      panelTabs: [
        { kind: "file", path: "outputs/notes.txt", fileName: "notes.txt" },
      ],
    });
  });

  it("creates Outputs for an initially open panel and preserves explicit resources", () => {
    store().createSession("open-files", { outputPanelMode: "medium" });
    expect(store().sessions.get("open-files")).toMatchObject({
      outputPanelMode: "medium",
      panelTabs: [{ kind: "outputs" }],
      activePanelTabId: "outputs",
    });
    store().createSession("explicit-file", {
      outputPanelMode: "medium",
      panelTabs: [{ kind: "file", path: oldFile.path, fileName: "old.pdf" }],
      activePanelTabId: `file:${oldFile.path}`,
    });
    expect(store().sessions.get("explicit-file")?.panelTabs).toHaveLength(1);
  });

  it("normalizes restored file selection with its tab identity", () => {
    store().createSession("legacy-normalized", {
      outputPanelMode: "medium",
      panelTabs: [
        { kind: "file", path: "outputs/./notes.txt", fileName: "notes.txt" },
      ],
      activePanelTabId: "file:outputs/./notes.txt",
    });
    expect(store().sessions.get("legacy-normalized")).toMatchObject({
      activePanelTabId: "file:outputs/notes.txt",
      panelTabs: [{ kind: "file", path: "outputs/notes.txt" }],
    });
  });

  it("keeps session tabs and widths isolated", () => {
    store().openFilePreview(sessionId, oldFile.path, "old.pdf");
    store().setCurrentMediumPanelProportion(0.7);
    store().setCurrentSession("other-session");
    expect(store().sessions.get("other-session")).toMatchObject({
      panelTabs: [],
      outputPanelMode: "closed",
      mediumPanelProportion: 0.5,
    });
    store().setCurrentSession(sessionId);
    expect(session()).toMatchObject({
      mediumPanelProportion: 0.7,
      activePanelTabId: `file:${oldFile.path}`,
    });
  });

  it("ignores a response for a deleted and recreated session", async () => {
    jest.mocked(fetchOutputInventory).mockImplementationOnce(async () => {
      store().createSession(sessionId);
      return { files: [slides], complete: true };
    });
    await store().refreshOutputInventory(sessionId);
    expect(session()?.outputInventory).toBeNull();
  });

  it("settles repeated mode requests in the latest state", () => {
    store().setCurrentOutputPanelMode("medium");
    store().setCurrentOutputPanelMode("full");
    store().setCurrentOutputPanelMode("closed");
    store().setCurrentOutputPanelMode("medium");
    expect(session()).toMatchObject({
      outputPanelMode: "medium",
    });
  });

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

  it("does not treat missing entries in a partial response as deletions", async () => {
    await refresh([oldFile, slides]);
    await refresh([slides], false);
    expect(session()?.outputInventory).toHaveProperty([oldFile.path], oldFile);
    expect(session()?.filesNeedsRefresh).toBe(0);
    await refresh([slides]);
    expect(session()?.outputInventory?.[oldFile.path]).toBeUndefined();
    expect(session()?.filesNeedsRefresh).toBe(1);
  });

  it("keeps passive partial and complete inventories from revealing tabs", async () => {
    await refresh([oldFile], false);
    expect(session()?.outputInventory).toEqual({ [oldFile.path]: oldFile });
    await refresh([oldFile, slides]);
    expect(session()).toMatchObject({
      outputPanelMode: "closed",
      panelTabs: [],
    });
  });

  it("discards a delayed response from an older turn", async () => {
    await refresh([]);
    jest.mocked(fetchOutputInventory).mockImplementationOnce(async () => {
      store().updateSessionData(sessionId, { turnGeneration: 1 });
      return { files: [slides], complete: true };
    });
    await store().refreshOutputInventory(sessionId);
    expect(session()).toMatchObject({
      outputPanelMode: "closed",
      outputInventory: {},
    });
  });

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
    expect(session()?.activePanelTabId).toBeNull();
  });

  it("coalesces repeated silent reads of the same runtime", async () => {
    let resolveRead: ((inventory: OutputInventory) => void) | undefined;
    jest.mocked(fetchOutputInventory).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRead = resolve;
      })
    );
    const reads = Array.from({ length: 12 }, () =>
      store().refreshOutputInventory(sessionId, { silent: true })
    );
    expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
    resolveRead?.({ files: [oldFile], complete: true });
    await Promise.all(reads);
    expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
    expect(session()?.outputInventory).toEqual({ [oldFile.path]: oldFile });
    expect(session()?.activePanelTabId).toBeNull();
  });

  it("validates idle filesystem writes without opening resource tabs", async () => {
    store().updateSessionData(sessionId, { status: "idle" });
    await refresh([oldFile]);
    jest.mocked(fetchOutputInventory).mockResolvedValueOnce({
      files: [oldFile, slides],
      complete: true,
    });
    store().triggerFilesRefresh(sessionId);
    await store().refreshOutputInventory(sessionId, { silent: true });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
    expect(session()).toMatchObject({
      outputInventory: { [oldFile.path]: oldFile, [slides.path]: slides },
      panelTabs: [],
    });
  });

  it("queues a post-write validation behind an older passive read", async () => {
    store().updateSessionData(sessionId, { status: "idle" });
    let resolveRead: ((inventory: OutputInventory) => void) | undefined;
    jest
      .mocked(fetchOutputInventory)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveRead = resolve;
        })
      )
      .mockResolvedValueOnce({ files: [oldFile, slides], complete: true });
    const beforeWrite = store().refreshOutputInventory(sessionId, {
      silent: true,
    });
    store().triggerFilesRefresh(sessionId);
    const afterWrite = store().refreshOutputInventory(sessionId, {
      silent: true,
    });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
    resolveRead?.({ files: [oldFile], complete: true });
    await Promise.all([beforeWrite, afterWrite]);
    expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
    expect(session()?.outputInventory).toEqual({
      [oldFile.path]: oldFile,
      [slides.path]: slides,
    });
  });

  it("leaves filesystem write discovery to streaming during active tasks", () => {
    store().updateSessionData(sessionId, { activeTurnId: "active-turn" });
    store().triggerFilesRefresh(sessionId);
    expect(fetchOutputInventory).not.toHaveBeenCalled();
    expect(session()?.filesNeedsRefresh).toBe(1);
  });

  it("keeps caller cancellation local and runs the next queued read", async () => {
    await refresh([oldFile]);
    const controller = new AbortController();
    let requestSignal: AbortSignal | undefined;
    jest
      .mocked(fetchOutputInventory)
      .mockImplementationOnce((_id, signal) => {
        requestSignal = signal;
        return new Promise((_resolve, reject) =>
          signal?.addEventListener("abort", () => reject(signal.reason), {
            once: true,
          })
        );
      })
      .mockResolvedValueOnce({ files: [oldFile, slides], complete: true });
    const cancelled = store().refreshOutputInventory(sessionId, {
      silent: true,
      signal: controller.signal,
    });
    const next = store().refreshOutputInventory(sessionId, { silent: true });
    controller.abort();
    await Promise.all([cancelled, next]);
    expect(requestSignal?.aborted).toBe(true);
    expect(fetchOutputInventory).toHaveBeenCalledTimes(3);
    expect(session()).toMatchObject({
      outputInventoryStatus: "complete",
      outputInventory: { [oldFile.path]: oldFile, [slides.path]: slides },
      activePanelTabId: null,
    });
  });

  it("queues a newer turn read separately from the previous turn", async () => {
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
    store().updateSessionData(sessionId, { turnGeneration: 1 });
    const second = store().refreshOutputInventory(sessionId, { silent: true });
    expect(fetchOutputInventory).toHaveBeenCalledTimes(1);
    resolveFirst?.({ files: [oldFile], complete: true });
    await first;
    expect(session()?.outputInventory).toBeNull();
    resolveSecond?.({ files: [oldFile, slides], complete: true });
    await second;
    await refresh([oldFile, slides]);
    expect(session()?.activePanelTabId).toBeNull();
    expect(session()?.outputInventory).toEqual({
      [oldFile.path]: oldFile,
      [slides.path]: slides,
    });
  });

  it("keeps inventory discovery independent of iframe remount", async () => {
    await refresh([oldFile]);
    let resolveRead: ((inventory: OutputInventory) => void) | undefined;
    jest.mocked(fetchOutputInventory).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRead = resolve;
      })
    );
    const read = store().refreshOutputInventory(sessionId, { silent: true });
    store().updateSessionData(sessionId, { webappNeedsRemount: 1 });
    resolveRead?.({ files: [oldFile, slides], complete: true });
    await read;
    expect(session()?.outputInventory).toEqual({
      [oldFile.path]: oldFile,
      [slides.path]: slides,
    });
  });

  it("aborts superseded runtimes without delaying their replacement", async () => {
    let oldSignal: AbortSignal | undefined;
    jest
      .mocked(fetchOutputInventory)
      .mockImplementationOnce((_id, signal) => {
        oldSignal = signal;
        return new Promise((_resolve, reject) =>
          signal?.addEventListener("abort", () => reject(signal.reason), {
            once: true,
          })
        );
      })
      .mockResolvedValueOnce({ files: [slides], complete: true });
    const first = store().refreshOutputInventory(sessionId, { silent: true });
    store().createSession(sessionId);
    const second = store().refreshOutputInventory(sessionId, { silent: true });
    expect(oldSignal?.aborted).toBe(true);
    expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
    await Promise.all([first, second]);
    expect(session()?.outputInventory).toEqual({ [slides.path]: slides });
  });

  it.each([401, 403, 404])(
    "purges inventory without retry after terminal errors (%s)",
    async (status) => {
      jest.spyOn(console, "warn").mockImplementation(() => {});
      await refresh([oldFile]);
      jest
        .mocked(fetchOutputInventory)
        .mockRejectedValueOnce(new FetchError("Unavailable", status, null));
      await store().refreshOutputInventory(sessionId, { silent: true });
      expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
      expect(session()).toMatchObject({
        outputInventory: null,
        outputInventoryStatus: "error",
        outputInventoryError: expect.objectContaining({ status }),
        outputBaselinePending: true,
      });
      await refresh([oldFile]);
      expect(session()?.outputInventoryError).toBeUndefined();
    }
  );

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

  it("does not retry an older turn after a new task starts", async () => {
    jest.useFakeTimers();
    await refresh([]);
    jest
      .mocked(fetchOutputInventory)
      .mockRejectedValueOnce(new Error("offline"));
    const discovery = store().refreshOutputInventory(sessionId);
    await jest.advanceTimersByTimeAsync(0);
    store().updateSessionData(sessionId, { turnGeneration: 1 });
    await jest.advanceTimersByTimeAsync(1000);
    await discovery;
    expect(fetchOutputInventory).toHaveBeenCalledTimes(2);
    jest.useRealTimers();
  });

  it("bounds stalled requests and preserves the inventory after retries fail", async () => {
    jest.useFakeTimers();
    const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
    await refresh([oldFile]);
    jest.mocked(fetchOutputInventory).mockImplementation(
      (_sessionId, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true }
          );
        })
    );
    const discovery = store().refreshOutputInventory(sessionId);
    await jest.advanceTimersByTimeAsync(108000);
    await discovery;
    expect(fetchOutputInventory).toHaveBeenCalledTimes(4);
    expect(session()).toMatchObject({
      outputInventory: { [oldFile.path]: oldFile },
    });
    warn.mockRestore();
    jest.useRealTimers();
  });
});

// --- Session deletion ---
describe("Session deletion", () => {
  const store = () => useBuildSessionStore.getState();

  function pendingDelete() {
    let resolve = () => {};
    const promise = new Promise<void>((complete) => {
      resolve = complete;
    });
    jest.mocked(deleteSession).mockReturnValue(promise);
    return resolve;
  }

  beforeEach(() => {
    jest.mocked(fetchSessionHistory).mockResolvedValue([]);
  });

  it("keeps the latest selected conversation when deleting a session finishes after navigation", async () => {
    panelPreferences.saveOutputPanelPreferences("session-a", {
      outputPanelMode: "medium",
      outputPanelInitialized: true,
      panelTabs: [{ kind: "files" }],
      activePanelTabId: "files",
      mediumPanelProportion: 0.5,
    });
    store().setCurrentSession("session-a");
    const finish = pendingDelete();
    const deletion = store().deleteBuildSession("session-a");
    store().setCurrentSession("session-b");
    store().openFilePreview("session-b", "outputs/current.md", "current.md");
    finish();
    await deletion;
    expect(store().currentSessionId).toBe("session-b");
    expect(store().sessions.get("session-b")).toMatchObject({
      activePanelTabId: "file:outputs/current.md",
      outputPanelMode: "medium",
    });
    expect(store().sessions.has("session-a")).toBe(false);
    expect(
      panelPreferences.readOutputPanelPreferences("session-a")
    ).toBeUndefined();
  });

  it("starts a fresh welcome output workspace after deleting the selected claimed session", async () => {
    store().openFilePreview(null, "outputs/private.md", "private.md");
    const claimedWorkspaceId = store().noSessionOutputWorkspaceId;
    store().createSession("claimed");
    store().setCurrentSession("claimed");
    expect(store().sessions.get("claimed")?.outputWorkspaceId).toBe(
      claimedWorkspaceId
    );
    const finish = pendingDelete();
    const deletion = store().deleteBuildSession("claimed");
    finish();
    await deletion;
    expect(store().currentSessionId).toBeNull();
    expect(store().noSessionOutputWorkspaceId).not.toBe(claimedWorkspaceId);
    expect(store().noSessionPanelTabs).toEqual([]);
    expect(store().noSessionActivePanelTabId).toBeNull();
    expect(store().noSessionOutputPanelInitialized).toBe(false);
    expect(store().noSessionOutputPanelMode).toBe("closed");
    expect(store().sessions.has("claimed")).toBe(false);
  });
});

// --- Store subscriptions ---
describe("Store subscriptions", () => {
  const sessionId = "chat-session";
  const store = () => useBuildSessionStore.getState();

  beforeEach(() => {
    store().createSession(sessionId);
    store().setCurrentSession(sessionId);
  });

  it("keeps the chat subscription stable when output tabs and layout change", () => {
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useChatSession();
    });
    const initial = result.current;
    const initialRenders = renders;
    act(() => {
      store().openFilesTab(sessionId);
      store().openFilePreview(sessionId, "outputs/report.md", "report.md");
      store().setActivePanelTabId(sessionId, "files");
      store().reorderPanelTab(sessionId, "files", 1);
      store().setCurrentOutputPanelMode("full");
      store().setCurrentMediumPanelProportion(0.6);
      store().closePanelTab(sessionId, "file:outputs/report.md");
    });
    expect(result.current).toBe(initial);
    expect(renders).toBe(initialRenders);
    expect(store().sessions.get(sessionId)).toMatchObject({
      outputPanelMode: "full",
      activePanelTabId: "files",
      mediumPanelProportion: 0.6,
    });
  });

  it("updates the chat subscription for new messages and task status", () => {
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useChatSession();
    });
    const initialRenders = renders;
    const message = {
      id: "message-1",
      type: "user" as const,
      content: "Build a report",
      timestamp: new Date(),
    };
    act(() => store().appendMessageToSession(sessionId, message));
    expect(result.current?.messages).toEqual([message]);
    expect(renders).toBeGreaterThan(initialRenders);
    const messageRenders = renders;
    act(() => store().updateSessionData(sessionId, { status: "running" }));
    expect(result.current?.status).toBe("running");
    expect(renders).toBeGreaterThan(messageRenders);
    const statusRenders = renders;
    act(() => store().updateSessionData(sessionId, { status: "running" }));
    expect(renders).toBe(statusRenders);
  });

  it("keeps the output session subscription stable while chat and output controls change", () => {
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useOutputSession();
    });
    const initial = result.current;
    const initialRenders = renders;
    act(() => {
      store().appendMessageToSession(sessionId, {
        id: "message-1",
        type: "user",
        content: "Build a report",
        timestamp: new Date(),
      });
      store().appendStreamItem(sessionId, {
        id: "text-1",
        type: "text",
        content: "Working",
        isStreaming: true,
      });
      store().openFilesTab(sessionId);
      store().openFilePreview(sessionId, "outputs/report.md", "report.md");
      store().setActivePanelTabId(sessionId, "files");
      store().setCurrentMediumPanelProportion(0.6);
    });
    expect(result.current).toBe(initial);
    expect(renders).toBe(initialRenders);
  });

  it("updates the output session subscription when inventory or runtime changes", () => {
    let renders = 0;
    const { result } = renderHook(() => {
      renders++;
      return useOutputSession();
    });
    const initialRenders = renders;
    const outputInventory = {
      "outputs/report.md": {
        path: "outputs/report.md",
        revision: "1",
        size: 10,
      },
    };
    act(() => store().updateSessionData(sessionId, { outputInventory }));
    expect(result.current?.outputInventory).toBe(outputInventory);
    expect(renders).toBeGreaterThan(initialRenders);
    const inventoryRenders = renders;
    act(() => store().updateSessionData(sessionId, { status: "running" }));
    expect(result.current?.status).toBe("running");
    expect(renders).toBeGreaterThan(inventoryRenders);
  });
});

// --- Queued messages ---
describe("Queued messages", () => {
  describe("Craft queued messages", () => {
    it("keeps attachments associated with their message across FIFO removal", () => {
      const sessionId = "session-1";
      const imageAttachments: BuildMessageAttachment[] = [
        {
          name: "reference.png",
          path: "attachments/reference.png",
          mimeType: "image/png",
        },
      ];
      const documentAttachments: BuildMessageAttachment[] = [
        {
          name: "brief.docx",
          path: "attachments/brief.docx",
          mimeType:
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
      ];

      useBuildSessionStore.getState().createSession(sessionId);
      useBuildSessionStore
        .getState()
        .enqueueMessage(sessionId, "Inspect this image", imageAttachments);
      useBuildSessionStore
        .getState()
        .enqueueMessage(sessionId, "Summarize this brief", documentAttachments);
      const queued = useBuildSessionStore.getState().sessions.get(sessionId)
        ?.queuedMessages[0];
      if (!queued) throw new Error("Missing queued message fixture");
      useBuildSessionStore.getState().removeQueuedMessage(sessionId, queued.id);

      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages
      ).toEqual([
        {
          id: expect.any(Number),
          text: "Summarize this brief",
          phase: "waiting",
          attachments: documentAttachments,
        },
      ]);
    });
  });
});

// --- Session loading and restoration ---
describe("Session loading and restoration", () => {
  const mockedApi = jest.mocked(api);

  const SESSION_ID = "11111111-1111-1111-1111-111111111111";

  function sleepingSession(): ApiDetailedSessionResponse {
    return {
      id: SESSION_ID,
      user_id: null,
      name: null,
      status: "idle",
      created_at: "2026-10-10T00:00:00Z",
      last_activity_at: "2026-10-10T00:00:00Z",
      artifacts: [],
      sharing_scope: "private",
      origin: "INTERACTIVE",
      agent_provider: null,
      agent_model: null,
      skills_stale: false,
      nextjs_port: null,
      session_loaded_in_sandbox: false,
      sandbox: {
        id: "sb1",
        status: "sleeping",
        container_id: null,
        created_at: "2026-10-10T00:00:00Z",
        last_heartbeat: null,
      },
    };
  }

  function runningSession(
    nextjsPort: number | null = null
  ): ApiDetailedSessionResponse {
    const session = sleepingSession();
    return {
      ...session,
      status: "active",
      nextjs_port: nextjsPort,
      session_loaded_in_sandbox: true,
      sandbox: session.sandbox
        ? { ...session.sandbox, status: "running" }
        : null,
    };
  }

  function webappInfo(has_webapp: boolean | null, ready: boolean): unknown {
    return { has_webapp, webapp_url: null, status: "running", ready };
  }

  function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve: (value: T) => void = () => {};
    const promise = new Promise<T>((resolvePromise) => {
      resolve = resolvePromise;
    });
    return { promise, resolve };
  }

  describe("loadSession restore status", () => {
    beforeEach(() => {
      mockedApi.fetchMessages.mockResolvedValue([] as never);
      mockedApi.fetchActiveTurn.mockResolvedValue(null as never);
      mockedApi.fetchKnownTurn.mockImplementation(
        async (sessionId, turnId) => ({
          session_id: sessionId,
          turn_id: turnId,
          status: "SUCCEEDED",
          turn_index: 0,
        })
      );
      mockedApi.fetchArtifacts.mockResolvedValue([] as never);
      mockedApi.fetchOutputInventory.mockResolvedValue({
        files: [],
        complete: true,
      });
      // Default: webapp already serving, so the readiness gate is a no-op.
      mockedApi.fetchWebappInfo.mockResolvedValue(
        webappInfo(true, true) as never
      );
    });

    it.each([
      ["running", "history"],
      ["failed", "history"],
      ["running", "runtime"],
      ["failed", "runtime"],
    ] as const)(
      "finishes metadata loading without replacing a newer %s turn started during %s loading",
      async (status, stage) => {
        const runtime =
          deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
        const history =
          deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
        mockedApi.fetchSession.mockReturnValueOnce(runtime.promise);
        mockedApi.fetchMessages.mockReturnValueOnce(history.promise);
        const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
        await waitFor(() => expect(mockedApi.fetchMessages).toHaveBeenCalled());
        if (stage === "runtime") await act(async () => history.resolve([]));
        useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
          turnGeneration: 1,
          agentProvider: "new-provider",
          agentModel: "new-model",
          status,
          error: status === "failed" ? "Send rejected" : null,
          activeTurnId: status === "running" ? "new-turn" : null,
          messages: [
            {
              id: "local",
              type: "user",
              content: "New prompt",
              timestamp: new Date(),
            },
          ],
        });
        history.resolve([]);
        runtime.resolve({
          ...runningSession(),
          agent_provider: "saved-provider",
          agent_model: "saved-model",
        } as never);
        await loading;
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ).toMatchObject({
          isLoaded: true,
          loadError: null,
          agentProvider: "new-provider",
          agentModel: "new-model",
          status,
          error: status === "failed" ? "Send rejected" : null,
          activeTurnId: status === "running" ? "new-turn" : null,
          messages: [{ content: "New prompt" }],
          sandbox: { status: "running" },
        });
        expect(mockedApi.fetchArtifacts).toHaveBeenCalled();
      }
    );

    it("keeps a rejected prompt and turn error when revisiting a loaded session", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession());
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        status: "active",
        error: "Token budget exceeded",
        messages: [
          {
            id: "rejected",
            type: "user",
            content: "Keep this prompt",
            timestamp: new Date(),
          },
        ],
        streamItems: [
          {
            type: "error",
            id: "budget-error",
            content: "Token budget exceeded",
          },
        ],
      });
      const rejected = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      useBuildSessionStore.getState().setCurrentSession("another-session");
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      expect(mockedApi.fetchSession).toHaveBeenCalledTimes(1);
      expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1);
      const revisited = useBuildSessionStore
        .getState()
        .sessions.get(SESSION_ID);
      expect(revisited?.messages).toBe(rejected?.messages);
      expect(revisited?.streamItems).toBe(rejected?.streamItems);
      expect(revisited?.error).toBe("Token budget exceeded");
    });

    it("ignores runtime discovery for a deleted and recreated session", async () => {
      const runtime = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
      mockedApi.fetchSession.mockReturnValueOnce(runtime.promise);
      const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
      await waitFor(() => {
        expect(mockedApi.fetchMessages).toHaveBeenCalled();
      });
      const oldInstance = useBuildSessionStore
        .getState()
        .sessions.get(SESSION_ID)?.instanceId;
      useBuildSessionStore.setState({
        sessions: new Map(),
        currentSessionId: null,
      });
      useBuildSessionStore.getState().createSession(SESSION_ID, {
        isLoaded: true,
        agentModel: "replacement-model",
      });
      const replacement = useBuildSessionStore
        .getState()
        .sessions.get(SESSION_ID);
      expect(replacement?.instanceId).not.toBe(oldInstance);
      runtime.resolve(sleepingSession());
      await loading;
      expect(useBuildSessionStore.getState().sessions.get(SESSION_ID)).toBe(
        replacement
      );
      expect(mockedApi.restoreSession).not.toHaveBeenCalled();
      expect(mockedApi.fetchArtifacts).not.toHaveBeenCalled();
    });

    it("does not let an older history read overwrite a settled transcript", async () => {
      const staleHistory =
        deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
      mockedApi.fetchSession.mockResolvedValue(runningSession());
      mockedApi.fetchMessages.mockReturnValueOnce(staleHistory.promise);
      const store = useBuildSessionStore.getState();
      store.createSession(SESSION_ID, {
        status: "running",
        isLoaded: true,
        turnGeneration: 1,
      });
      const loading = store.loadSession(SESSION_ID, { force: true });
      await waitFor(() =>
        expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1)
      );
      mockedApi.fetchMessages.mockResolvedValue([
        {
          id: "confirmed",
          type: "assistant",
          content: "Final answer",
          message_metadata: {
            streamItems: [
              {
                type: "text",
                id: "confirmed-text",
                content: "Final answer",
                isStreaming: false,
              },
            ],
          },
          timestamp: new Date(),
          turn_index: 0,
        },
      ]);
      await store.beginTurnSettlement(
        SESSION_ID,
        { kind: "interactive", turnId: "completed-turn" },
        1
      );
      staleHistory.resolve([]);
      await loading;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.messages
      ).toEqual([
        expect.objectContaining({ id: "confirmed", content: "Final answer" }),
      ]);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.turnSettlement
          ?.phase
      ).toBe("ready");
    });

    it.each([false, true])(
      "loads saved model metadata after an early send unless an accepted selection changed it (%s)",
      async (changedSelection) => {
        const runtime =
          deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
        mockedApi.fetchSession.mockReturnValueOnce(runtime.promise);
        const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
        await waitFor(() => expect(mockedApi.fetchMessages).toHaveBeenCalled());
        useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
          status: "running",
          turnGeneration: 1,
          activeTurnId: "early-turn",
          ...(changedSelection && {
            agentProvider: "selected-provider",
            agentModel: "selected-model",
          }),
        });
        runtime.resolve({
          ...runningSession(),
          agent_provider: "saved-provider",
          agent_model: "saved-model",
        } as never);
        await loading;
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ).toMatchObject({
          isLoaded: true,
          activeTurnId: "early-turn",
          status: "running",
          agentProvider: changedSelection
            ? "selected-provider"
            : "saved-provider",
          agentModel: changedSelection ? "selected-model" : "saved-model",
        });
      }
    );

    it("rejects a queued handoff during restoration without an interactive owner", () => {
      const store = useBuildSessionStore.getState();
      store.createSession(SESSION_ID, {
        status: "creating",
        activeTurnId: null,
        activeTurnLocalOwner: false,
      });
      expect(store.enqueueMessage(SESSION_ID, "keep this draft", [])).toBe(
        false
      );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages
      ).toEqual([]);
      store.updateSessionData(SESSION_ID, { activeTurnLocalOwner: true });
      expect(store.enqueueMessage(SESSION_ID, "real pending turn", [])).toBe(
        true
      );
    });

    it("shows persisted history before runtime discovery completes", async () => {
      const runtime = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
      mockedApi.fetchSession.mockReturnValueOnce(runtime.promise);
      mockedApi.fetchMessages.mockResolvedValueOnce([
        {
          id: "persisted-user",
          type: "user",
          content: "Saved conversation",
          created_at: "2026-10-09T00:00:00Z",
        },
      ] as never);
      mockedApi.restoreSession.mockResolvedValueOnce(runningSession() as never);
      const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);

      await waitFor(() => {
        const session = useBuildSessionStore
          .getState()
          .sessions.get(SESSION_ID);
        expect(session?.isLoaded).toBe(false);
        expect(session?.messages[0]?.content).toBe("Saved conversation");
      });
      expect(mockedApi.restoreSession).not.toHaveBeenCalled();
      expect(mockedApi.fetchArtifacts).not.toHaveBeenCalled();
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.sandbox
      ).toBeNull();

      runtime.resolve({
        ...sleepingSession(),
        agent_provider: "saved-provider",
        agent_model: "saved-model",
      } as never);
      await loading;
      expect(mockedApi.restoreSession).toHaveBeenCalledWith(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: true,
        agentProvider: "saved-provider",
        agentModel: "saved-model",
        sandbox: { status: "running" },
        filesNeedsRefresh: 1,
      });
    });

    it("retains loaded history after runtime discovery fails and retries on revisit", async () => {
      mockedApi.fetchSession
        .mockRejectedValueOnce(new Error("Runtime unavailable"))
        .mockResolvedValueOnce(runningSession() as never);
      mockedApi.fetchMessages.mockResolvedValue([
        {
          id: "persisted-user",
          type: "user",
          content: "Saved conversation",
          created_at: "2026-10-09T00:00:00Z",
        },
      ] as never);
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: false,
        error: null,
        loadError: "Runtime unavailable",
      });
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.messages[0]
          ?.content
      ).toBe("Saved conversation");

      useBuildSessionStore.getState().setCurrentSession("another-session");
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      expect(mockedApi.fetchSession).toHaveBeenCalledTimes(2);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: true,
        error: null,
        loadError: null,
        sandbox: { status: "running" },
      });
    });

    it("starts inventory loading before artifact discovery finishes", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession());
      const artifacts =
        deferred<Awaited<ReturnType<typeof api.fetchArtifacts>>>();
      mockedApi.fetchArtifacts.mockReturnValueOnce(artifacts.promise);
      const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
      await waitFor(() =>
        expect(mockedApi.fetchOutputInventory).toHaveBeenCalledTimes(1)
      );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: true,
        sandbox: { status: "running" },
      });
      artifacts.resolve([]);
      await loading;
    });

    it("revalidates outputs on a cached session revisit without reloading history", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession());
      const store = useBuildSessionStore.getState();
      await store.loadSession(SESSION_ID);
      await store.refreshOutputInventory(SESSION_ID, { silent: true });
      mockedApi.fetchOutputInventory.mockClear();
      mockedApi.fetchMessages.mockClear();
      mockedApi.fetchSession.mockClear();
      await store.loadSession(SESSION_ID);
      await waitFor(() =>
        expect(mockedApi.fetchOutputInventory).toHaveBeenCalledTimes(1)
      );
      expect(mockedApi.fetchMessages).not.toHaveBeenCalled();
      expect(mockedApi.fetchSession).not.toHaveBeenCalled();
    });

    it("loads the session while its inventory is still pending", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      const inventory =
        deferred<Awaited<ReturnType<typeof api.fetchOutputInventory>>>();
      mockedApi.fetchOutputInventory.mockReturnValueOnce(inventory.promise);
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: true,
        outputInventory: null,
      });
      inventory.resolve({ files: [], complete: true });
      // Wait for the serialized queue to settle before resetting the store.
      await useBuildSessionStore
        .getState()
        .refreshOutputInventory(SESSION_ID, { silent: true });
    });

    it("keeps the sandbox running when the post-restore artifact fetch fails", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
      // Artifacts list the sandbox via opencode-serve and can fail right after
      // the pod comes up — this must NOT flip the sandbox to "failed".
      mockedApi.fetchArtifacts.mockRejectedValue(
        new Error("opencode not ready")
      );

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("running");
      expect(session?.filesNeedsRefresh).toBe(1);
    });

    it("invalidates even an empty directory cache only after restoration finishes", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      const restore =
        deferred<Awaited<ReturnType<typeof api.restoreSession>>>();
      const started = deferred<void>();
      mockedApi.restoreSession.mockImplementation(() => {
        started.resolve();
        return restore.promise;
      });
      const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
      await started.promise;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        sandbox: { status: "restoring" },
        filesNeedsRefresh: 0,
      });
      restore.resolve(runningSession() as never);
      await loading;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        sandbox: { status: "running" },
        filesNeedsRefresh: 1,
      });
    });

    it("replaces in-flight inventory even when restore keeps the sandbox id", async () => {
      const store = useBuildSessionStore.getState;
      store().createSession(SESSION_ID, {
        sandbox: runningSession().sandbox as never,
      });
      let oldSignal: AbortSignal | undefined;
      mockedApi.fetchOutputInventory
        .mockImplementationOnce((_id, signal) => {
          oldSignal = signal;
          return new Promise((_resolve, reject) =>
            signal?.addEventListener("abort", () => reject(signal.reason), {
              once: true,
            })
          );
        })
        .mockResolvedValueOnce({ files: [], complete: true });
      const oldRead = store().refreshOutputInventory(SESSION_ID, {
        silent: true,
      });
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
      await store().loadSession(SESSION_ID);
      await oldRead;
      expect(oldSignal?.aborted).toBe(true);
      expect(mockedApi.fetchOutputInventory).toHaveBeenCalledTimes(2);
      await waitFor(() =>
        expect(store().sessions.get(SESSION_ID)?.outputInventory).toEqual({})
      );
    });

    it("finishes filesystem restoration before the app is ready", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
      const readiness =
        deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
      mockedApi.fetchWebappInfo.mockReturnValueOnce(readiness.promise);
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        sandbox: { status: "running" },
        filesNeedsRefresh: 1,
        webappNeedsRemount: 0,
      });
      expect(mockedApi.fetchOutputInventory).toHaveBeenCalled();
      readiness.resolve(webappInfo(true, true) as never);
      await waitFor(() =>
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
            ?.webappNeedsRemount
        ).toBe(1)
      );
    });

    it("keeps restored app readiness across a successor load", async () => {
      mockedApi.fetchSession.mockResolvedValueOnce(sleepingSession() as never);
      mockedApi.restoreSession.mockResolvedValueOnce(runningSession() as never);
      const readiness =
        deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
      mockedApi.fetchWebappInfo.mockReturnValueOnce(readiness.promise);
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      mockedApi.fetchSession.mockResolvedValueOnce(runningSession() as never);
      await useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      expect(mockedApi.restoreSession).toHaveBeenCalledTimes(1);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
          ?.webappNeedsRemount
      ).toBe(0);
      readiness.resolve(webappInfo(true, true) as never);
      await waitFor(() =>
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
            ?.webappNeedsRemount
        ).toBe(1)
      );
    });

    it("ignores delayed app readiness after the sandbox is replaced", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
      const readiness =
        deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
      mockedApi.fetchWebappInfo.mockReturnValueOnce(readiness.promise);
      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      useBuildSessionStore
        .getState()
        .updateSessionData(SESSION_ID, { sandbox: null });
      readiness.resolve(webappInfo(true, true) as never);
      await act(async () => {});
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({ sandbox: null, webappNeedsRemount: 0 });
    });

    it("builds the webapp URL from the session port", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession(3210) as never);
      mockedApi.fetchArtifacts.mockResolvedValue([
        { type: "web_app" },
      ] as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.webappUrl
      ).toBe("http://localhost:3210");
    });

    it("keeps newer session data when concurrent force loads finish out of order", async () => {
      const older = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
      const newer = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
      mockedApi.fetchSession
        .mockReturnValueOnce(older.promise)
        .mockReturnValueOnce(newer.promise);
      const latestMessages = [
        {
          id: "latest-message",
          type: "user",
          content: "latest transcript",
          created_at: "2026-10-09T00:00:00Z",
        },
      ];
      mockedApi.fetchMessages.mockResolvedValue(latestMessages as never);
      const first = useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      const second = useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      newer.resolve({ ...runningSession(), agent_model: "new-model" } as never);
      await second;
      await useBuildSessionStore
        .getState()
        .refreshOutputInventory(SESSION_ID, { silent: true });
      const latestSession = useBuildSessionStore
        .getState()
        .sessions.get(SESSION_ID);
      expect(latestSession).toMatchObject({
        agentModel: "new-model",
        sandbox: { status: "running" },
      });
      expect(latestSession?.messages[0]?.content).toBe("latest transcript");

      mockedApi.fetchMessages.mockResolvedValue([]);
      older.resolve({
        ...sleepingSession(),
        agent_model: "old-model",
      } as never);
      await first;
      expect(useBuildSessionStore.getState().sessions.get(SESSION_ID)).toBe(
        latestSession
      );
      expect(mockedApi.restoreSession).not.toHaveBeenCalled();
      expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1);
    });

    it("marks the sandbox failed when restore itself fails", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession.mockRejectedValue(new Error("restore boom"));

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("failed");
    });

    it.each(["restore", "readiness"] as const)(
      "finishes %s readiness without replacing a newer turn",
      async (stage) => {
        mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
        const restore =
          deferred<Awaited<ReturnType<typeof api.restoreSession>>>();
        const readiness =
          deferred<Awaited<ReturnType<typeof api.fetchWebappInfo>>>();
        mockedApi.restoreSession.mockReturnValueOnce(restore.promise);
        mockedApi.fetchWebappInfo.mockReset();
        mockedApi.fetchWebappInfo.mockReturnValue(readiness.promise);
        const loading = useBuildSessionStore.getState().loadSession(SESSION_ID);
        await waitFor(() =>
          expect(mockedApi.restoreSession).toHaveBeenCalled()
        );
        if (stage === "readiness") {
          restore.resolve(runningSession() as never);
          await waitFor(() =>
            expect(mockedApi.fetchWebappInfo).toHaveBeenCalled()
          );
        }
        useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
          turnGeneration: 1,
          status: "running",
          activeTurnId: "newer-turn",
        });

        restore.resolve(runningSession() as never);
        readiness.resolve(webappInfo(true, true) as never);
        await loading;
        await waitFor(() =>
          expect(
            useBuildSessionStore.getState().sessions.get(SESSION_ID)
              ?.webappNeedsRemount
          ).toBe(1)
        );
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ).toMatchObject({
          status: "running",
          activeTurnId: "newer-turn",
          sandbox: { status: "running" },
          filesNeedsRefresh: 1,
          webappNeedsRemount: 1,
        });
        expect(mockedApi.fetchArtifacts).toHaveBeenCalledWith(SESSION_ID);
        expect(mockedApi.fetchArtifacts).toHaveBeenCalledTimes(1);
      }
    );

    it("preserves a newer turn when the older restoration fails", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      let rejectRestore: (error: Error) => void = () => {};
      mockedApi.restoreSession.mockReturnValueOnce(
        new Promise((_, reject) => {
          rejectRestore = reject;
        })
      );
      const loading: Promise<void> = useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID);
      await waitFor(() => expect(mockedApi.restoreSession).toHaveBeenCalled());
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        turnGeneration: 1,
        status: "running",
        activeTurnId: "newer-turn",
      });
      rejectRestore(new Error("Restore unavailable"));
      await loading;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        status: "running",
        activeTurnId: "newer-turn",
        sandbox: { status: "failed" },
      });
    });

    it("retries a failed restoration when the session is revisited", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession
        .mockRejectedValueOnce(new Error("restore unavailable"))
        .mockResolvedValueOnce(runningSession() as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: true,
        sandbox: { status: "failed" },
      });

      useBuildSessionStore.getState().setCurrentSession("another-session");
      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      expect(mockedApi.restoreSession).toHaveBeenCalledTimes(2);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        isLoaded: true,
        sandbox: { status: "running" },
      });
    });

    it("clears stale skills after a successful session restore", async () => {
      mockedApi.fetchSession.mockResolvedValue({
        ...sleepingSession(),
        skills_stale: true,
      } as never);
      mockedApi.restoreSession.mockResolvedValue({
        ...runningSession(),
        skills_stale: false,
      } as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(false);
    });

    it("waits for the webapp before flipping to running, then shows running", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
      // Webapp not ready on the first poll, ready on the second.
      mockedApi.fetchWebappInfo
        .mockResolvedValueOnce(webappInfo(true, false) as never)
        .mockResolvedValue(webappInfo(true, true) as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      // It consulted webapp readiness, and the final state is running.
      expect(mockedApi.fetchWebappInfo).toHaveBeenCalled();
      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.sandbox?.status).toBe("running");
    });

    it("remounts the preview on restore, while edits only refresh (HMR handles them)", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      mockedApi.restoreSession.mockResolvedValue(runningSession() as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      let session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.webappNeedsRefresh).toBe(1);
      expect(session?.webappNeedsRemount).toBe(1);

      // A web/ file edit mid-turn must not remount the iframe.
      useBuildSessionStore.getState().triggerWebappRefresh(SESSION_ID);
      session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.webappNeedsRefresh).toBe(2);
      expect(session?.webappNeedsRemount).toBe(1);
    });

    it("renders a persisted turn-error row when it is the latest activity", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchMessages.mockResolvedValue([
        {
          id: "user-1",
          type: "user",
          content: "Do a thing",
          timestamp: new Date(),
          message_metadata: {
            type: "user_message",
            content: { type: "text", text: "Do a thing" },
          },
        },
        {
          id: "error-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "error",
            message: "This turn was stopped after reaching its time limit.",
          },
        },
      ] as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      const assistant = session?.messages.find((message) => {
        return message.type === "assistant";
      });
      expect(assistant?.message_metadata?.streamItems).toEqual([
        {
          type: "error",
          id: "error-1",
          content: "This turn was stopped after reaching its time limit.",
        },
      ]);
    });

    it("drops a persisted turn-error row once later activity exists", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchMessages.mockResolvedValue([
        {
          id: "user-1",
          type: "user",
          content: "Do a thing",
          timestamp: new Date(),
          message_metadata: {
            type: "user_message",
            content: { type: "text", text: "Do a thing" },
          },
        },
        {
          id: "error-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "error",
            message: "This turn was stopped after reaching its time limit.",
          },
        },
        {
          id: "user-2",
          type: "user",
          content: "Continue",
          timestamp: new Date(),
          message_metadata: {
            type: "user_message",
            content: { type: "text", text: "Continue" },
          },
        },
        {
          id: "answer-2",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_message",
            content: { type: "text", text: "Continued and finished." },
          },
        },
      ] as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      const allItems = (session?.messages ?? [])
        .filter((message) => message.type === "assistant")
        .flatMap(
          (message) =>
            (message.message_metadata?.streamItems ?? []) as { type: string }[]
        );
      expect(allItems.some((item) => item.type === "error")).toBe(false);
      expect(allItems.some((item) => item.type === "text")).toBe(true);
    });

    it("restores persisted agent thought packets as collapsed transcript stream items", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchMessages.mockResolvedValue([
        {
          id: "user-1",
          type: "user",
          content: "Build a dashboard",
          timestamp: new Date(),
          message_metadata: {
            type: "user_message",
            content: { type: "text", text: "Build a dashboard" },
          },
        },
        {
          id: "thought-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_thought",
            content: { type: "text", text: "Inspecting available files." },
          },
        },
        {
          id: "answer-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_message",
            content: { type: "text", text: "Created the dashboard." },
          },
        },
      ] as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      const assistant = session?.messages.find((message) => {
        return message.type === "assistant";
      });
      const streamItems = assistant?.message_metadata?.streamItems;

      expect(streamItems).toEqual([
        {
          type: "thinking",
          id: "thought-1",
          content: "Inspecting available files.",
          isStreaming: false,
        },
        {
          type: "text",
          id: "answer-1",
          content: "Created the dashboard.",
          isStreaming: false,
        },
      ]);
    });

    it("keeps child-routed text and thinking out of the parent transcript", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchMessages.mockResolvedValue([
        {
          id: "user-1",
          type: "user",
          content: "Build a dashboard",
          timestamp: new Date(),
          message_metadata: {
            type: "user_message",
            content: { type: "text", text: "Build a dashboard" },
          },
        },
        {
          id: "child-thought-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_thought",
            content: { type: "text", text: "Child thinking." },
            _meta: {
              sessionId: "child-session-1",
              parentSessionId: SESSION_ID,
            },
          },
        },
        {
          id: "child-answer-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_message",
            content: { type: "text", text: "Child answer." },
            _meta: {
              sessionId: "child-session-1",
              parentSessionId: SESSION_ID,
            },
          },
        },
      ] as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.messages).toEqual([
        expect.objectContaining({ id: "user-1", type: "user" }),
      ]);
      expect(session?.subagents.get("child-session-1")?.turns[0]).toMatchObject(
        {
          thinking: "Child thinking.",
          response: "Child answer.",
          streamItems: [
            expect.objectContaining({
              type: "thinking",
              content: "Child thinking.",
              isStreaming: false,
            }),
            expect.objectContaining({
              type: "text",
              content: "Child answer.",
              isStreaming: false,
            }),
          ],
        }
      );
    });

    it.each([true, false])(
      "restores child transcript with task fallback (child events: %s)",
      async (hasChildEvents) => {
        mockedApi.fetchSession.mockResolvedValue(runningSession());
        const childMessages = hasChildEvents
          ? [
              {
                id: "child-prefix",
                type: "assistant" as const,
                content: "",
                timestamp: new Date(),
                message_metadata: {
                  type: "agent_message",
                  content: { type: "text", text: "First part." },
                  _meta: {
                    sessionId: "child-session-1",
                    parentSessionId: SESSION_ID,
                    partId: "first-part",
                  },
                },
              },
              {
                id: "child-tool",
                type: "assistant" as const,
                content: "",
                timestamp: new Date(),
                message_metadata: {
                  type: "tool_call_progress",
                  tool_call_id: "child-tool-1",
                  kind: "read",
                  status: "completed",
                  raw_input: {},
                  raw_output: {},
                  _meta: {
                    sessionId: "child-session-1",
                    parentSessionId: SESSION_ID,
                  },
                },
              },
              {
                id: "child-final",
                type: "assistant" as const,
                content: "",
                timestamp: new Date(),
                message_metadata: {
                  type: "agent_message",
                  content: { type: "text", text: "Final part." },
                  _meta: {
                    sessionId: "child-session-1",
                    parentSessionId: SESSION_ID,
                    partId: "final-part",
                  },
                },
              },
            ]
          : [];
        mockedApi.fetchMessages.mockResolvedValue([
          ...childMessages,
          {
            id: "parent-task",
            type: "assistant",
            content: "",
            timestamp: new Date(),
            message_metadata: {
              type: "tool_call_progress",
              tool_call_id: "task-1",
              kind: "task",
              status: "completed",
              raw_input: { prompt: "Inspect files" },
              raw_output: {
                output:
                  "task_id: child-session-1\n\n<task_result>Final part.</task_result>",
              },
            },
          },
          {
            id: "parent-task-repeated",
            type: "assistant",
            content: "",
            timestamp: new Date(),
            message_metadata: {
              type: "tool_call_progress",
              tool_call_id: "task-1",
              kind: "task",
              status: "completed",
              raw_input: { prompt: "Inspect files" },
              raw_output: {
                output:
                  "task_id: child-session-1\n\n<task_result>Final part.</task_result>",
              },
            },
          },
        ]);
        await useBuildSessionStore.getState().loadSession(SESSION_ID);
        const turn = useBuildSessionStore
          .getState()
          .sessions.get(SESSION_ID)
          ?.subagents.get("child-session-1")?.turns[0];
        expect(turn?.response).toBe(
          hasChildEvents ? "First part.Final part." : "Final part."
        );
        expect(turn?.streamItems).toEqual(
          hasChildEvents
            ? [
                expect.objectContaining({
                  type: "text",
                  partId: "first-part",
                  content: "First part.",
                  isStreaming: false,
                }),
                expect.objectContaining({ type: "tool_call" }),
                expect.objectContaining({
                  type: "text",
                  partId: "final-part",
                  content: "Final part.",
                  isStreaming: false,
                }),
              ]
            : [
                expect.objectContaining({
                  type: "text",
                  content: "Final part.",
                  isStreaming: false,
                }),
              ]
        );
      }
    );

    it("restores subagent prompt and logs when parent task output carries the child id", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchMessages.mockResolvedValue([
        {
          id: "user-1",
          type: "user",
          content: "Build a game",
          timestamp: new Date(),
          message_metadata: {
            type: "user_message",
            content: { type: "text", text: "Build a game" },
          },
        },
        {
          id: "child-thought-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_thought",
            content: { type: "text", text: "Child thinking." },
            _meta: {
              sessionId: "child-session-1",
              parentSessionId: SESSION_ID,
            },
          },
        },
        {
          id: "child-answer-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "agent_message",
            content: { type: "text", text: "Child answer." },
            _meta: {
              sessionId: "child-session-1",
              parentSessionId: SESSION_ID,
            },
          },
        },
        {
          id: "task-progress-1",
          type: "assistant",
          content: "",
          timestamp: new Date(),
          message_metadata: {
            type: "tool_call_progress",
            tool_call_id: "task-call-1",
            kind: "task",
            status: "completed",
            raw_input: {
              description: "Build Space Invaders game",
              prompt:
                "You are building ONE retro arcade game as a single React component.",
            },
            raw_output: {
              output:
                "task_id: child-session-1 (for resuming to continue this task if needed)\n\n<task_result>Child answer.</task_result>",
            },
          },
        },
      ] as never);

      await useBuildSessionStore.getState().loadSession(SESSION_ID);

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.subagents.get("child-session-1")).toMatchObject({
        parentToolCallId: "task-call-1",
        name: "Build Space Invaders game",
        status: "done",
        turns: [
          expect.objectContaining({
            prompt:
              "You are building ONE retro arcade game as a single React component.",
            thinking: "Child thinking.",
            response: "Child answer.",
            streamItems: [
              expect.objectContaining({ type: "thinking" }),
              expect.objectContaining({
                type: "text",
                content: "Child answer.",
              }),
            ],
          }),
        ],
      });

      const assistant = session?.messages.find(
        (message) => message.type === "assistant"
      );
      expect(assistant?.message_metadata?.streamItems).toEqual([
        expect.objectContaining({
          type: "tool_call",
          id: "task-call-1",
        }),
      ]);
    });

    it("preserves live turn metadata when active turn lookup fails", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchActiveTurn.mockRejectedValue(
        new Error("turn endpoint unavailable")
      );
      useBuildSessionStore.getState().createSession(SESSION_ID, {
        status: "running",
        messages: [
          {
            id: "local-user",
            type: "user",
            content: "hello",
            timestamp: new Date(),
          },
        ],
        activeTurnId: "turn-live",
        activeTurnLocalOwner: false,
        isLoaded: false,
      });

      await useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.status).toBe("running");
      expect(session?.activeTurnId).toBe("turn-live");
      expect(session?.activeTurnLocalOwner).toBe(false);
    });

    it("retains fetched stale-skill state during a pre-provisioned turn", async () => {
      mockedApi.fetchSession.mockResolvedValue({
        ...runningSession(),
        skills_stale: true,
      } as never);
      useBuildSessionStore.getState().createSession(SESSION_ID, {
        status: "running",
        messages: [
          {
            id: "local-user",
            type: "user",
            content: "hello",
            timestamp: new Date(),
          },
        ],
        skillsStale: false,
        isLoaded: false,
      });

      await useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });

      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(true);
    });

    it("clears cached stale-skill state when loading a current runtime", async () => {
      mockedApi.fetchSession.mockResolvedValue({
        ...runningSession(),
        skills_stale: false,
      } as never);
      useBuildSessionStore
        .getState()
        .createSession(SESSION_ID, { skillsStale: true, isLoaded: false });
      await useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(false);
    });

    it("rejects a load fetched before a newer stale-skill update", async () => {
      const messages = deferred<unknown[]>();
      mockedApi.fetchSession.mockResolvedValue({
        ...runningSession(),
        skills_stale: true,
      } as never);
      mockedApi.fetchMessages.mockReturnValue(messages.promise as never);

      const load = useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      await Promise.resolve();
      await Promise.resolve();
      expect(mockedApi.fetchMessages).toHaveBeenCalled();

      useBuildSessionStore
        .getState()
        .updateSessionData(SESSION_ID, { skillsStale: false });
      messages.resolve([]);
      await load;

      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(false);
    });

    it("clears stale turn metadata when active turn lookup says no turn is running", async () => {
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchActiveTurn.mockResolvedValue(null as never);
      useBuildSessionStore.getState().createSession(SESSION_ID, {
        status: "running",
        activeTurnId: "turn-stale",
        activeTurnLocalOwner: false,
        isLoaded: false,
      });

      await useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });

      const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
      expect(session?.status).toBe("active");
      expect(session?.activeTurnId).toBeNull();
      expect(session?.activeTurnLocalOwner).toBe(false);
    });
  });

  describe("completed transcript handoff", () => {
    const user = {
      id: "user-db",
      type: "user" as const,
      content: "Build it",
      timestamp: new Date(),
      turn_index: 0,
    };
    const answer = {
      id: "answer-local",
      type: "assistant" as const,
      content: "Complete answer",
      message_metadata: {
        streamItems: [
          {
            type: "text",
            id: "answer-text",
            content: "Complete answer",
            isStreaming: false,
          },
        ],
      },
      timestamp: new Date(),
      turn_index: 0,
    };
    const receipt = {
      owner: { kind: "interactive" as const, turnId: "completed-turn" },
      turnGeneration: 0,
      phase: "ready" as const,
    };

    beforeEach(() => {
      jest.clearAllMocks();
      useBuildSessionStore.setState({
        sessions: new Map(),
        currentSessionId: null,
      });
      mockedApi.fetchSession.mockResolvedValue(runningSession() as never);
      mockedApi.fetchActiveTurn.mockResolvedValue(null);
      mockedApi.fetchKnownTurn.mockImplementation(
        async (sessionId, turnId) => ({
          session_id: sessionId,
          turn_id: turnId,
          status: "SUCCEEDED",
          turn_index: 0,
        })
      );
      mockedApi.fetchMessages.mockResolvedValue([user, answer]);
      mockedApi.fetchArtifacts.mockResolvedValue([]);
      mockedApi.fetchOutputInventory.mockResolvedValue({
        files: [],
        complete: true,
      });
      useBuildSessionStore.getState().createSession(SESSION_ID, {
        status: "running",
        isLoaded: true,
        messages: [user, answer],
        activeTurnId: "completed-turn",
      });
    });

    it.each(["FAILED", "expired"] as const)(
      "does not release queued work after %s completion",
      async (outcome) => {
        const store = useBuildSessionStore.getState();
        store.enqueueMessage(SESSION_ID, "next task", []);
        mockedApi.fetchKnownTurn.mockResolvedValue(
          outcome === "expired"
            ? null
            : {
                session_id: SESSION_ID,
                turn_id: "completed-turn",
                turn_index: 0,
                status: outcome,
                error_detail: outcome === "FAILED" ? "provider failed" : null,
              }
        );
        await store.beginTurnSettlement(
          SESSION_ID,
          { kind: "interactive", turnId: "completed-turn" },
          0
        );
        const session = useBuildSessionStore
          .getState()
          .sessions.get(SESSION_ID);
        expect(
          useBuildSessionStore.getState().claimQueuedMessage(SESSION_ID)
        ).toBeNull();
        expect(session?.queuedMessages).toHaveLength(1);
        if (outcome === "expired") {
          expect(session?.turnSettlement?.phase).toBe("failed");
        } else {
          expect(session?.status).toBe("failed");
          expect(session?.messages).toHaveLength(2);
        }
      }
    );

    it("adopts a running successor even when its predecessor failed", async () => {
      mockedApi.fetchKnownTurn.mockResolvedValue({
        session_id: SESSION_ID,
        turn_id: "completed-turn",
        turn_index: 0,
        status: "FAILED",
        error_detail: "old provider failed",
      });
      mockedApi.fetchActiveTurn.mockResolvedValue({
        session_id: SESSION_ID,
        turn_id: "other-tab-turn",
        turn_index: 1,
        status: "RUNNING",
      });
      await useBuildSessionStore
        .getState()
        .beginTurnSettlement(
          SESSION_ID,
          { kind: "interactive", turnId: "completed-turn" },
          0
        );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        status: "running",
        activeTurnId: "other-tab-turn",
        error: null,
        turnSettlement: null,
      });
    });

    it("releases queued work after confirmed cancellation from another client", async () => {
      mockedApi.fetchKnownTurn.mockResolvedValue({
        session_id: SESSION_ID,
        turn_id: "completed-turn",
        turn_index: 0,
        status: "CANCELLED",
      });
      await useBuildSessionStore
        .getState()
        .beginTurnSettlement(
          SESSION_ID,
          { kind: "interactive", turnId: "completed-turn" },
          0
        );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.turnSettlement
          ?.phase
      ).toBe("ready");
    });

    it("holds the streamed response until the server turn completes", async () => {
      jest.useFakeTimers();
      try {
        mockedApi.fetchActiveTurn.mockResolvedValue({
          turn_id: "completed-turn",
          turn_index: 0,
        } as never);
        mockedApi.fetchMessages.mockResolvedValue([user]);
        const settling = useBuildSessionStore
          .getState()
          .beginTurnSettlement(
            SESSION_ID,
            { kind: "interactive", turnId: "completed-turn" },
            0
          );
        await jest.advanceTimersByTimeAsync(0);
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)?.messages
        ).toEqual([user, answer]);
        expect(mockedApi.fetchMessages).not.toHaveBeenCalled();
        const persisted = {
          ...answer,
          id: "canonical-answer",
          content: "Saved answer",
          message_metadata: {
            streamItems: [
              {
                type: "text",
                id: "saved-text",
                content: "Saved answer",
                isStreaming: false,
              },
            ],
          },
        };
        mockedApi.fetchActiveTurn.mockResolvedValue(null);
        mockedApi.fetchMessages.mockResolvedValue([user, persisted]);
        await jest.advanceTimersByTimeAsync(1000);
        await settling;
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ).toMatchObject({
          messages: [user, persisted],
          status: "active",
          turnSettlement: receipt,
        });
      } finally {
        jest.useRealTimers();
      }
    });

    it.each(["FAILED", "SKIPPED"] as const)(
      "hydrates %s scheduled history without permitting queued work",
      async (status) => {
        const store = useBuildSessionStore.getState();
        store.updateSessionData(SESSION_ID, {
          activeTurnId: null,
          activeTurnLocalOwner: false,
          messages: [user],
        });
        store.enqueueMessage(SESSION_ID, "next prompt", []);
        mockedApi.fetchScheduledRunContext.mockResolvedValue({
          run_id: "scheduled-run",
          task_id: "task",
          task_name: "Report",
          status,
          started_at: "2026-10-10T00:00:00Z",
          finished_at: "2026-10-10T00:01:00Z",
        });
        mockedApi.fetchMessages.mockResolvedValue([user, answer]);
        await store.beginTurnSettlement(
          SESSION_ID,
          { kind: "scheduled", runId: "scheduled-run" },
          0
        );
        expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1);
        expect(mockedApi.fetchActiveTurn).not.toHaveBeenCalled();
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ).toMatchObject({
          messages: [user, answer],
          status: "failed",
          turnSettlement: null,
        });
        expect(store.claimQueuedMessage(SESSION_ID)).toBeNull();
      }
    );

    it("retains failed scheduled history recovery until its canonical read succeeds", async () => {
      const store = useBuildSessionStore.getState();
      store.updateSessionData(SESSION_ID, {
        activeTurnId: null,
        activeTurnLocalOwner: false,
        messages: [user],
      });
      store.enqueueMessage(SESSION_ID, "next prompt", []);
      mockedApi.fetchScheduledRunContext.mockResolvedValue({
        run_id: "scheduled-run",
        task_id: "task",
        task_name: "Report",
        status: "FAILED",
        started_at: "2026-10-10T00:00:00Z",
        finished_at: "2026-10-10T00:01:00Z",
      });
      mockedApi.fetchMessages.mockRejectedValueOnce(
        new Error("History unavailable")
      );
      await store.beginTurnSettlement(
        SESSION_ID,
        { kind: "scheduled", runId: "scheduled-run" },
        0
      );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        messages: [user],
        turnSettlement: { phase: "failed", error: "History unavailable" },
      });
      expect(store.claimQueuedMessage(SESSION_ID)).toBeNull();
      mockedApi.fetchMessages.mockResolvedValue([user, answer]);
      await store.retryTurnSettlement(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        messages: [user, answer],
        status: "failed",
        turnSettlement: null,
      });
      expect(store.claimQueuedMessage(SESSION_ID)).toBeNull();
    });

    it("waits for the scheduled worker to commit completion before reading history", async () => {
      jest.useFakeTimers();
      try {
        const run = {
          run_id: "scheduled-run",
          task_id: "task",
          task_name: "Daily report",
          status: "RUNNING" as const,
          started_at: "2026-10-10T00:00:00Z",
          finished_at: null,
        };
        useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
          activeTurnId: null,
          activeTurnLocalOwner: false,
        });
        const owner = { kind: "scheduled" as const, runId: run.run_id };
        mockedApi.fetchScheduledRunContext.mockResolvedValue(run);
        const settling = useBuildSessionStore
          .getState()
          .beginTurnSettlement(SESSION_ID, owner, 0);
        await jest.advanceTimersByTimeAsync(0);
        expect(mockedApi.fetchActiveTurn).not.toHaveBeenCalled();
        expect(mockedApi.fetchMessages).not.toHaveBeenCalled();
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)?.messages
        ).toEqual([user, answer]);
        mockedApi.fetchScheduledRunContext.mockResolvedValue({
          ...run,
          status: "SUCCEEDED",
          finished_at: "2026-10-10T00:01:00Z",
        });
        await jest.advanceTimersByTimeAsync(1000);
        await settling;
        expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1);
        expect(mockedApi.fetchActiveTurn).not.toHaveBeenCalled();
        expect(
          useBuildSessionStore.getState().sessions.get(SESSION_ID)
            ?.turnSettlement
        ).toEqual({ owner, turnGeneration: 0, phase: "ready" });
      } finally {
        jest.useRealTimers();
      }
    });

    it("settles without waiting for runtime restoration", async () => {
      mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
      await useBuildSessionStore
        .getState()
        .beginTurnSettlement(
          SESSION_ID,
          { kind: "interactive", turnId: "completed-turn" },
          0
        );
      expect(mockedApi.fetchSession).not.toHaveBeenCalled();
      expect(mockedApi.restoreSession).not.toHaveBeenCalled();
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.turnSettlement
      ).toEqual(receipt);
    });

    it("does not replace a newer turn during completion polling", async () => {
      jest.useFakeTimers();
      try {
        mockedApi.fetchActiveTurn.mockResolvedValue({
          turn_id: "completed-turn",
          turn_index: 0,
        } as never);
        const settling = useBuildSessionStore
          .getState()
          .beginTurnSettlement(
            SESSION_ID,
            { kind: "interactive", turnId: "completed-turn" },
            0
          );
        await jest.advanceTimersByTimeAsync(0);
        useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
          turnGeneration: 1,
          status: "running",
          activeTurnId: "newer-turn",
          turnSettlement: null,
        });
        const current = useBuildSessionStore
          .getState()
          .sessions.get(SESSION_ID);
        await jest.advanceTimersByTimeAsync(1000);
        await settling;
        expect(useBuildSessionStore.getState().sessions.get(SESSION_ID)).toBe(
          current
        );
        expect(mockedApi.fetchMessages).not.toHaveBeenCalled();
      } finally {
        jest.useRealTimers();
      }
    });

    it("uses the canonical transcript after completion even when its text differs", async () => {
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        streamItems: [
          {
            type: "text",
            id: "live-answer",
            content: "Complete answer",
            isStreaming: false,
          },
        ],
      });
      const persisted = {
        ...answer,
        id: "answer-db",
        content: "Canonical answer",
        message_metadata: {
          streamItems: [
            {
              type: "text",
              id: "canonical-text",
              content: "Canonical answer",
              isStreaming: false,
            },
          ],
        },
      };
      mockedApi.fetchMessages.mockResolvedValue([user, persisted]);
      await useBuildSessionStore
        .getState()
        .beginTurnSettlement(
          SESSION_ID,
          { kind: "interactive", turnId: "completed-turn" },
          0
        );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        messages: [user, persisted],
        streamItems: [],
        turnSettlement: receipt,
      });
      expect(
        mockedApi.fetchActiveTurn.mock.invocationCallOrder[0]
      ).toBeLessThan(
        mockedApi.fetchMessages.mock.invocationCallOrder[0] ?? Infinity
      );
    });

    it("retains the response on a completion lookup failure and allows retry", async () => {
      mockedApi.fetchActiveTurn.mockRejectedValueOnce(
        new Error("turn endpoint unavailable")
      );
      await useBuildSessionStore
        .getState()
        .beginTurnSettlement(
          SESSION_ID,
          { kind: "interactive", turnId: "completed-turn" },
          0
        );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        messages: [user, answer],
        turnSettlement: { phase: "failed", error: "turn endpoint unavailable" },
      });
      await useBuildSessionStore.getState().retryTurnSettlement(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.turnSettlement
      ).toEqual(receipt);
    });

    it("does not release held completion through a forced history load", async () => {
      const settlement = {
        ...receipt,
        phase: "failed" as const,
        error: "history unavailable",
      };
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        status: "idle",
        activeTurnId: null,
        turnSettlement: settlement,
      });
      mockedApi.fetchMessages.mockResolvedValue([user]);
      await useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({ messages: [user, answer], turnSettlement: settlement });
    });

    it("preserves completion learned after a history load started", async () => {
      const messages =
        deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
      mockedApi.fetchMessages.mockReturnValueOnce(messages.promise);
      const loading = useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      await waitFor(() =>
        expect(mockedApi.fetchMessages).toHaveBeenCalledTimes(1)
      );
      await useBuildSessionStore
        .getState()
        .beginTurnSettlement(
          SESSION_ID,
          { kind: "interactive", turnId: "completed-turn" },
          0
        );
      messages.resolve([user]);
      await loading;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({ messages: [user, answer], turnSettlement: receipt });
    });

    it("keeps a newer live turn's identity when completion lookup fails", async () => {
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        activeTurnId: "next-turn",
        activeTurnIndex: 1,
        activeTurnLocalOwner: true,
      });
      mockedApi.fetchActiveTurn.mockRejectedValue(
        new Error("turn endpoint unavailable")
      );
      mockedApi.fetchMessages.mockResolvedValue([user]);
      await useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        messages: [user, answer],
        status: "running",
        activeTurnId: "next-turn",
        activeTurnIndex: 1,
        activeTurnLocalOwner: true,
      });
    });

    it("rejects a history response from an older turn", async () => {
      const messages =
        deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
      mockedApi.fetchMessages.mockReturnValueOnce(messages.promise);
      const loading = useBuildSessionStore
        .getState()
        .loadSession(SESSION_ID, { force: true });
      await waitFor(() => expect(mockedApi.fetchMessages).toHaveBeenCalled());
      useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
        turnGeneration: 1,
        status: "running",
        activeTurnId: "next-turn",
      });
      messages.resolve([user]);
      await loading;
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({
        messages: [user, answer],
        status: "running",
        activeTurnId: "next-turn",
      });
    });
  });

  describe("waitForWebappReady", () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });
    afterEach(() => {
      jest.useRealTimers();
    });

    it("returns immediately when the session has no webapp", async () => {
      mockedApi.fetchWebappInfo.mockResolvedValue(
        webappInfo(false, false) as never
      );
      const pending = waitForWebappReady(SESSION_ID);
      await jest.advanceTimersByTimeAsync(30000);
      await pending;
      expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(1);
    });

    it("returns immediately when the webapp is already ready", async () => {
      mockedApi.fetchWebappInfo.mockResolvedValue(
        webappInfo(true, true) as never
      );
      const pending = waitForWebappReady(SESSION_ID);
      await jest.advanceTimersByTimeAsync(30000);
      await pending;
      expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(1);
    });

    it("polls until the webapp reports ready", async () => {
      mockedApi.fetchWebappInfo
        .mockResolvedValueOnce(webappInfo(true, false) as never)
        .mockResolvedValueOnce(webappInfo(true, false) as never)
        .mockResolvedValue(webappInfo(true, true) as never);
      const pending = waitForWebappReady(SESSION_ID);
      await jest.advanceTimersByTimeAsync(30000);
      await pending;
      expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(3);
    });

    it("stops at the deadline when the webapp never comes up", async () => {
      mockedApi.fetchWebappInfo.mockResolvedValue(
        webappInfo(true, false) as never
      );
      const pending = waitForWebappReady(SESSION_ID);
      await jest.advanceTimersByTimeAsync(30000);
      await expect(pending).resolves.toBe(false);
      expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(20);
    });

    it("keeps polling through transient fetch errors", async () => {
      mockedApi.fetchWebappInfo
        .mockRejectedValueOnce(new Error("sandbox not reachable"))
        .mockResolvedValue(webappInfo(true, true) as never);
      const pending = waitForWebappReady(SESSION_ID);
      await jest.advanceTimersByTimeAsync(30000);
      await pending;
      expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(2);
    });

    it("keeps polling while webapp existence is unknown", async () => {
      mockedApi.fetchWebappInfo
        .mockResolvedValueOnce(webappInfo(null, false) as never)
        .mockResolvedValue(webappInfo(false, false) as never);
      const pending = waitForWebappReady(SESSION_ID);
      await jest.advanceTimersByTimeAsync(30000);
      await pending;
      expect(mockedApi.fetchWebappInfo).toHaveBeenCalledTimes(2);
    });
  });
});

// --- Automatic webapp selection ---
describe("Automatic webapp selection", () => {
  const sessionId = "auto-webapp";
  const store = () => useBuildSessionStore.getState();
  beforeEach(() => {
    store().createSession(sessionId);
    store().setCurrentSession(sessionId);
    jest
      .mocked(fetchWebappInfo)
      .mockResolvedValue({ has_webapp: true, ready: true } as never);
  });
  it("starts app discovery from the artifact event without a mounted chat panel", async () => {
    store().addArtifactToSession(sessionId, {
      id: "app-artifact",
      session_id: sessionId,
      type: "web_app",
      name: "Local App",
      path: "outputs/web",
      preview_url: null,
      created_at: new Date(),
      updated_at: new Date(),
    });
    await waitFor(() =>
      expect(store().sessions.get(sessionId)?.panelTabs).toContainEqual(
        expect.objectContaining({ kind: "browser", appId: sessionId })
      )
    );
    expect(fetchWebappInfo).toHaveBeenCalledTimes(1);
  });

  it("opens the local app and keeps Outputs available", async () => {
    await store().maybeAutoOpenWebapp(sessionId);
    const session = store().sessions.get(sessionId);
    expect(session).toMatchObject({
      outputPanelMode: "medium",
      outputSelectionLocked: true,
    });
    expect(session?.panelTabs).toEqual([
      { kind: "outputs" },
      expect.objectContaining({ kind: "browser", appId: sessionId }),
    ]);
  });
  it.each(["medium", "closed"] as const)(
    "preserves restored %s panel state",
    async (mode) => {
      const restoredId = "restored-webapp";
      panelPreferences.saveOutputPanelPreferences(restoredId, {
        outputPanelMode: mode,
        outputPanelInitialized: true,
        panelTabs: [
          { kind: "file", path: "outputs/heart.png", fileName: "heart.png" },
        ],
        activePanelTabId: "file:outputs/heart.png",
        mediumPanelProportion: 0.5,
        filesTabState: { expandedPaths: [], scrollTop: 0 },
      });
      store().setCurrentSession(restoredId);
      await store().maybeAutoOpenWebapp(restoredId);
      expect(fetchWebappInfo).not.toHaveBeenCalled();
      expect(store().sessions.get(restoredId)).toMatchObject({
        activePanelTabId: "file:outputs/heart.png",
        outputPanelMode: mode,
        outputSelectionLocked: true,
      });
      store().updateSessionData(restoredId, { outputSelectionLocked: false });
      await store().maybeAutoOpenWebapp(restoredId);
      expect(
        store()
          .sessions.get(restoredId)
          ?.panelTabs.some((tab) => tab.kind === "browser")
      ).toBe(true);
    }
  );
  it("reuses an existing local app tab", async () => {
    const tab = { kind: "browser" as const, id: "existing", appId: sessionId };
    store().updateSessionData(sessionId, {
      panelTabs: [tab],
      outputPanelInitialized: true,
    });
    await store().maybeAutoOpenWebapp(sessionId);
    expect(store().sessions.get(sessionId)?.panelTabs).toEqual([tab]);
    expect(store().sessions.get(sessionId)?.activePanelTabId).toBe(
      "browser:existing"
    );
  });
  it("shares readiness checks and respects navigation while waiting", async () => {
    let finish:
      | ((info: Awaited<ReturnType<typeof fetchWebappInfo>>) => void)
      | undefined;
    jest.mocked(fetchWebappInfo).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        })
    );
    const first = store().maybeAutoOpenWebapp(sessionId);
    const second = store().maybeAutoOpenWebapp(sessionId);
    store().openFilesTab(sessionId);
    finish?.({ has_webapp: true, ready: true } as never);
    await Promise.all([first, second]);
    expect(fetchWebappInfo).toHaveBeenCalledTimes(1);
    expect(store().sessions.get(sessionId)?.activePanelTabId).toBe("files");
    expect(
      store()
        .sessions.get(sessionId)
        ?.panelTabs.some((tab) => tab.kind === "browser")
    ).toBe(false);
  });
  it.each(["turn", "sandbox", "instance"])(
    "rejects readiness after a %s change",
    async (change) => {
      let finish:
        | ((info: Awaited<ReturnType<typeof fetchWebappInfo>>) => void)
        | undefined;
      jest.mocked(fetchWebappInfo).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          })
      );
      const request = store().maybeAutoOpenWebapp(sessionId);
      const session = store().sessions.get(sessionId)!;
      store().updateSessionData(
        sessionId,
        change === "turn"
          ? { turnGeneration: session.turnGeneration + 1 }
          : change === "instance"
            ? { instanceId: "replacement" }
            : { sandbox: { id: "replacement", status: "running" } as never }
      );
      finish?.({ has_webapp: true, ready: true } as never);
      await request;
      expect(store().sessions.get(sessionId)?.panelTabs).toEqual([]);
    }
  );
  it.each(["dismissed", "interrupting", "interrupted", "failed"])(
    "does not auto-open when %s",
    async (reason) => {
      store().updateSessionData(sessionId, {
        outputSelectionLocked: reason === "dismissed",
        isInterrupting: reason === "interrupting",
        wasInterrupted: reason === "interrupted",
        status: reason === "failed" ? "failed" : "running",
      });
      await store().maybeAutoOpenWebapp(sessionId);
      expect(fetchWebappInfo).not.toHaveBeenCalled();
      expect(store().sessions.get(sessionId)?.panelTabs).toEqual([]);
    }
  );
  it("does not open an absent app", async () => {
    jest
      .mocked(fetchWebappInfo)
      .mockResolvedValue({ has_webapp: false, ready: false } as never);
    await store().maybeAutoOpenWebapp(sessionId);
    expect(store().sessions.get(sessionId)?.panelTabs).toEqual([]);
  });
  it("refresh events also discover the app", async () => {
    store().triggerWebappRefresh(sessionId);
    await waitFor(() =>
      expect(store().sessions.get(sessionId)?.outputSelectionLocked).toBe(true)
    );
  });
});

describe("session history races and discarded queued starts", () => {
  const sessionId = "ownership-race";
  const active: NonNullable<Awaited<ReturnType<typeof api.fetchActiveTurn>>> = {
    session_id: sessionId,
    turn_id: "external-turn",
    status: "RUNNING",
    turn_index: 0,
  };
  beforeEach(() => {
    jest.resetAllMocks();
    jest
      .mocked(api.fetchKnownTurn)
      .mockImplementation(async (sessionId, turnId) => ({
        session_id: sessionId,
        turn_id: turnId,
        status: "SUCCEEDED",
        turn_index: 0,
      }));

    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    jest.mocked(api.fetchActiveTurn).mockResolvedValue(null);
    jest.mocked(api.fetchMessages).mockResolvedValue([]);
    jest.mocked(api.fetchArtifacts).mockResolvedValue([]);
    jest
      .mocked(api.fetchOutputInventory)
      .mockResolvedValue({ files: [], complete: true });
    jest.mocked(api.fetchSession).mockResolvedValue({
      id: sessionId,
      user_id: "user",
      name: "History",
      status: "active",
      created_at: "2026-10-12",
      last_activity_at: "2026-10-12",
      nextjs_port: null,
      sandbox: {
        id: "sandbox",
        status: "running",
        container_id: null,
        created_at: "2026-10-12",
        last_heartbeat: null,
      },
      artifacts: [],
      sharing_scope: "private",
      origin: "INTERACTIVE",
      agent_provider: null,
      agent_model: null,
      skills_stale: false,
      session_loaded_in_sandbox: true,
    });
  });
  afterEach(() => jest.useRealTimers());

  it("adopts a successor found after history and keeps its partial answer active", async () => {
    const latestHistory =
      deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
    jest
      .mocked(api.fetchActiveTurn)
      .mockResolvedValueOnce(null)
      .mockResolvedValue(active);
    jest
      .mocked(api.fetchMessages)
      .mockResolvedValueOnce([])
      .mockReturnValueOnce(latestHistory.promise);
    const store = useBuildSessionStore.getState();
    store.createSession(sessionId);
    store.updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "completed-turn",
      turnGeneration: 1,
    });
    store.enqueueMessage(sessionId, "Waiting prompt", []);
    const settling = store.beginTurnSettlement(
      sessionId,
      { kind: "interactive", turnId: "completed-turn" },
      1
    );
    await act(async () => {});
    expect(store.claimQueuedMessage(sessionId)).toBeNull();
    latestHistory.resolve([
      {
        id: "successor-user",
        type: "user",
        content: "External question",
        timestamp: new Date(),
        turn_index: 0,
      },
      {
        id: "successor-answer",
        type: "assistant",
        content: "Partial answer",
        timestamp: new Date(),
        turn_index: 0,
        message_metadata: {
          streamItems: [
            {
              id: "answer-part",
              partId: "answer-part",
              type: "text",
              content: "Partial answer",
              isStreaming: false,
            },
          ],
        },
      },
    ]);
    await settling;
    const restored = useBuildSessionStore.getState().sessions.get(sessionId);
    expect(restored).toMatchObject({
      activeTurnId: active.turn_id,
      turnGeneration: 2,
      status: "running",
      turnSettlement: null,
    });
    expect(restored?.messages).toEqual([
      expect.objectContaining({ id: "successor-user" }),
    ]);
    expect(restored?.streamItems).toEqual([
      expect.objectContaining({
        partId: "answer-part",
        content: "Partial answer",
      }),
    ]);
    expect(store.claimQueuedMessage(sessionId)).toBeNull();
  });

  it("does not install a successor when the completion owner changes during its history reread", async () => {
    const latestHistory =
      deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
    jest
      .mocked(api.fetchActiveTurn)
      .mockResolvedValueOnce(null)
      .mockResolvedValue(active);
    jest
      .mocked(api.fetchMessages)
      .mockResolvedValueOnce([])
      .mockReturnValueOnce(latestHistory.promise);
    const store = useBuildSessionStore.getState();
    store.createSession(sessionId);
    store.updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "completed-turn",
      turnGeneration: 1,
    });
    const settling = store.beginTurnSettlement(
      sessionId,
      { kind: "interactive", turnId: "completed-turn" },
      1
    );
    await act(async () => {});
    store.updateSessionData(sessionId, {
      turnGeneration: 2,
      activeTurnId: "local-successor",
      activeTurnLocalOwner: true,
      turnSettlement: null,
    });
    latestHistory.resolve([]);
    await settling;
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      activeTurnId: "local-successor",
      activeTurnLocalOwner: true,
      turnGeneration: 2,
    });
  });

  it("retains a successor observed before history when the next lookup is empty", async () => {
    jest
      .mocked(api.fetchActiveTurn)
      .mockResolvedValueOnce(active)
      .mockResolvedValueOnce(null);
    const store = useBuildSessionStore.getState();
    store.createSession(sessionId);
    store.updateSessionData(sessionId, {
      status: "running",
      activeTurnId: "completed-turn",
      turnGeneration: 1,
    });
    await store.beginTurnSettlement(
      sessionId,
      { kind: "interactive", turnId: "completed-turn" },
      1
    );
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      activeTurnId: active.turn_id,
      status: "running",
      turnSettlement: null,
    });
    expect(api.fetchMessages).toHaveBeenCalledTimes(1);
  });

  it("keeps a failed load disabled until the retry installs its runtime", async () => {
    const history = deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
    jest.mocked(api.fetchMessages).mockReturnValueOnce(history.promise);
    const store = useBuildSessionStore.getState();
    store.createSession(sessionId);
    store.updateSessionData(sessionId, { loadError: "Previous load failed" });
    const loading = store.loadSession(sessionId);
    await act(async () => {});
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.loadError
    ).toBe("Previous load failed");
    history.resolve([]);
    await loading;
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.loadError
    ).toBeNull();
  });

  it.each([null, "previous-turn"])(
    "loads the new prompt before adopting a turn that replaced %s",
    async (previousTurnId) => {
      const latestHistory =
        deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
      jest
        .mocked(api.fetchMessages)
        .mockResolvedValueOnce([])
        .mockReturnValueOnce(latestHistory.promise);
      jest
        .mocked(api.fetchActiveTurn)
        .mockResolvedValueOnce(
          previousTurnId ? { ...active, turn_id: previousTurnId } : null
        )
        .mockResolvedValueOnce(active);
      const loading = useBuildSessionStore.getState().loadSession(sessionId);
      await waitFor(() => expect(api.fetchMessages).toHaveBeenCalledTimes(2));
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)?.activeTurnId
      ).toBeNull();
      latestHistory.resolve([
        {
          id: "external-user",
          type: "user",
          content: "New external prompt",
          timestamp: new Date(),
          turn_index: 0,
        },
      ]);
      await loading;
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        activeTurnId: active.turn_id,
        messages: [{ content: "New external prompt" }],
      });
      expect(api.fetchActiveTurn).toHaveBeenCalledTimes(2);
    }
  );

  it.each(["starts", "completes"] as const)(
    "retains an external turn that %s during the history read",
    async (transition) => {
      const history = deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
      jest.mocked(api.fetchMessages).mockReturnValueOnce(history.promise);
      jest
        .mocked(api.fetchActiveTurn)
        .mockResolvedValueOnce(transition === "starts" ? null : active)
        .mockResolvedValueOnce(transition === "starts" ? active : null);
      const loading = useBuildSessionStore.getState().loadSession(sessionId);
      await waitFor(() => expect(api.fetchMessages).toHaveBeenCalled());
      expect(api.fetchActiveTurn).toHaveBeenCalledTimes(1);
      history.resolve([
        {
          id: "external-user",
          type: "user",
          content: "External task",
          timestamp: new Date(),
          turn_index: 0,
        },
      ]);
      await loading;
      expect(api.fetchActiveTurn).toHaveBeenCalledTimes(2);
      expect(
        useBuildSessionStore.getState().sessions.get(sessionId)
      ).toMatchObject({
        isLoaded: true,
        status: "running",
        activeTurnId: active.turn_id,
        activeTurnIndex: 0,
      });
    }
  );

  it("observes an accepted turn when its lost start response is discarded", async () => {
    jest.useFakeTimers();
    jest.mocked(api.fetchActiveTurn).mockResolvedValue(active);
    const store = useBuildSessionStore.getState();
    store.createSession(sessionId);
    store.enqueueMessage(sessionId, "Lost response", []);
    store.enqueueMessage(sessionId, "Next prompt", []);
    const queued =
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages ??
      [];
    const head = queued[0];
    if (!head) throw new Error("Missing queued fixture");
    store.updateSessionData(sessionId, {
      status: "failed",
      error: "Lost start response",
      turnGeneration: 3,
      queuedMessages: queued.map((item) =>
        item.id === head.id ? { ...item, phase: "failed" } : item
      ),
    });
    store.removeQueuedMessage(sessionId, head.id);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(31_000);
    });
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      status: "running",
      activeTurnId: active.turn_id,
      activeTurnIndex: active.turn_index,
      activeTurnLocalOwner: false,
      turnSettlement: null,
      queuedMessages: [
        expect.objectContaining({ text: "Next prompt", phase: "waiting" }),
      ],
    });
    expect(store.claimQueuedMessage(sessionId)).toBeNull();
  });

  it("reconciles a discarded failed start before releasing the next queued prompt", async () => {
    jest.useFakeTimers();
    const history = deferred<Awaited<ReturnType<typeof api.fetchMessages>>>();
    jest.mocked(api.fetchMessages).mockReturnValueOnce(history.promise);
    jest.mocked(api.fetchActiveTurn).mockResolvedValue(null);
    const store = useBuildSessionStore.getState();
    store.createSession(sessionId);
    store.enqueueMessage(sessionId, "Failed head", []);
    store.enqueueMessage(sessionId, "Next prompt", []);
    const queued =
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages ??
      [];
    store.updateSessionData(sessionId, {
      status: "failed",
      error: "Lost start response",
      turnGeneration: 3,
      queuedMessages: queued.map((item, index) =>
        index === 0 ? { ...item, phase: "failed" } : item
      ),
    });
    if (!queued[0]) throw new Error("Missing failed queue head");
    store.removeQueuedMessage(sessionId, queued[0].id);
    expect(store.claimQueuedMessage(sessionId)).toBeNull();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      error: null,
      status: "running",
      turnSettlement: {
        phase: "reconciling",
        owner: { kind: "interactive", turnId: null },
      },
    });
    expect(api.fetchMessages).not.toHaveBeenCalled();
    await act(async () => {});
    expect(api.fetchMessages).toHaveBeenCalledTimes(1);
    expect(store.claimQueuedMessage(sessionId)).toBeNull();
    history.resolve([]);
    await act(async () => {});
    expect(store.claimQueuedMessage(sessionId)).toMatchObject({
      text: "Next prompt",
      phase: "waiting",
    });
  });

  it("does not release an unrelated failure when removing a waiting queue tail", () => {
    const store = useBuildSessionStore.getState();
    store.createSession(sessionId);
    store.enqueueMessage(sessionId, "Failed head", []);
    store.enqueueMessage(sessionId, "Waiting tail", []);
    const queued =
      useBuildSessionStore.getState().sessions.get(sessionId)?.queuedMessages ??
      [];
    store.updateSessionData(sessionId, {
      status: "failed",
      error: "Start failed",
      queuedMessages: queued.map((item, index) =>
        index === 0 ? { ...item, phase: "failed" } : item
      ),
    });
    if (!queued[1]) throw new Error("Missing waiting queue tail");
    store.removeQueuedMessage(sessionId, queued[1].id);
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)
    ).toMatchObject({
      error: "Start failed",
      status: "failed",
      turnSettlement: null,
    });
    expect(api.fetchActiveTurn).not.toHaveBeenCalled();
  });
});

describe("deleting a live session", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    jest.mocked(api.fetchSessionHistory).mockResolvedValue([]);
  });

  it.each([false, true])(
    "aborts the live owner only after successful deletion (success: %s)",
    async (success) => {
      const store = useBuildSessionStore.getState();
      const controller = new AbortController();
      store.createSession("delete-live", {
        status: "running",
        activeTurnId: "live-turn",
        activeTurnLocalOwner: true,
        abortController: controller,
      });
      let resolve: (() => void) | undefined;
      let reject: ((error: Error) => void) | undefined;
      jest.mocked(api.deleteSession).mockReturnValueOnce(
        new Promise<void>((complete, fail) => {
          resolve = complete;
          reject = fail;
        })
      );
      const errorLog = jest
        .spyOn(console, "error")
        .mockImplementation(() => {});
      try {
        const deleting = store.deleteBuildSession("delete-live");
        expect(controller.signal.aborted).toBe(false);
        expect(
          useBuildSessionStore.getState().sessions.get("delete-live")
            ?.abortController
        ).toBe(controller);
        if (success) {
          resolve?.();
          await deleting;
          expect(controller.signal.aborted).toBe(true);
          expect(
            useBuildSessionStore.getState().sessions.has("delete-live")
          ).toBe(false);
        } else {
          const failure = new FetchError("Session busy", 409, null);
          reject?.(failure);
          await expect(deleting).rejects.toBe(failure);
          const session = useBuildSessionStore
            .getState()
            .sessions.get("delete-live");
          expect(controller.signal.aborted).toBe(false);
          expect(session?.abortController).toBe(controller);
          expect(session).toMatchObject({
            activeTurnId: "live-turn",
            activeTurnLocalOwner: true,
            status: "running",
          });
        }
      } finally {
        errorLog.mockRestore();
      }
    }
  );
});
