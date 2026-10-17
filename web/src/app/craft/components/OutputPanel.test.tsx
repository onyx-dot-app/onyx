import PdfDocumentViewer from "@/app/craft/components/output-panel/PdfDocumentViewer";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  cleanup,
  deferred,
} from "@tests/setup/test-utils";
import BuildOutputPanel from "@/app/craft/components/OutputPanel";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { downloadFile } from "@/lib/download";
import {
  downloadArtifactFile,
  exportDocx,
  fetchWebappInfo,
  fetchDirectoryListing,
  fetchFileContent,
  fetchOutputInventory,
  fetchPptxPreview,
  fetchOutputCards,
} from "@/app/craft/services/apiServices";
import type { OutputInventory } from "@/app/craft/types/streamingTypes";

const mockPreviewRender = jest.fn();
let mockRenderActualResources = false;
const mockPreviewLoadingCallbacks = new Map<
  string,
  (pending: boolean) => void
>();

jest.mock("@/lib/users/hooks", () => ({
  useCurrentUser: () => ({ user: { id: "test-user" } }),
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: "test-user" } }),
}));

jest.mock("@/lib/download", () => ({ downloadFile: jest.fn() }));

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchArtifacts: jest.fn().mockResolvedValue([]),
  fetchOutputCards: jest.fn().mockResolvedValue([]),
  fetchDirectoryListing: jest.fn(),
  fetchFileContent: jest.fn(),
  fetchOutputInventory: jest.fn(),
  fetchPptxPreview: jest.fn(),
  downloadArtifactFile: jest.fn(),
  exportDocx: jest.fn(),
  fetchWebappInfo: jest
    .fn()
    .mockResolvedValue({ has_webapp: false, ready: false }),
}));
jest.mock("@/app/craft/components/output-panel/UrlBar", () => {
  const ActualUrlBar = jest.requireActual<
    typeof import("@/app/craft/components/output-panel/UrlBar")
  >("@/app/craft/components/output-panel/UrlBar").default;
  function MockUrlBar(props: Parameters<typeof ActualUrlBar>[0]) {
    if (mockRenderActualResources) return <ActualUrlBar {...props} />;
    const {
      onRefresh,
      isRefreshing,
      isUserRefreshing,
      onDownload,
      displayUrl,
    } = props;
    return (
      <>
        <span data-testid="resource-location">{displayUrl}</span>
        <button
          onClick={onRefresh}
          aria-busy={isRefreshing}
          data-user-refreshing={isUserRefreshing}
          disabled={isRefreshing}
        >
          Refresh
        </button>
        {onDownload && <button onClick={onDownload}>Export DOCX</button>}
      </>
    );
  }
  return { __esModule: true, default: MockUrlBar };
});
jest.mock("@/app/craft/components/output-panel/FilesTab", () => {
  const ActualFilesTab = jest.requireActual<
    typeof import("@/app/craft/components/output-panel/FilesTab")
  >("@/app/craft/components/output-panel/FilesTab").default;
  function MockFilesTab(props: Parameters<typeof ActualFilesTab>[0]) {
    if (mockRenderActualResources) return <ActualFilesTab {...props} />;
    const { onRefreshingChange, isActive } = props;
    return (
      <div data-testid="files-body" data-active={isActive}>
        <button onClick={() => onRefreshingChange?.(true)}>
          Start folder read
        </button>
        <button onClick={() => onRefreshingChange?.(false)}>
          Finish folder read
        </button>
      </div>
    );
  }
  return { __esModule: true, default: MockFilesTab };
});

jest.mock("@/app/craft/components/output-panel/FilePreviewContent", () => {
  const ActualFilePreviewContent = jest.requireActual<
    typeof import("@/app/craft/components/output-panel/FilePreviewContent")
  >(
    "@/app/craft/components/output-panel/FilePreviewContent"
  ).FilePreviewContent;
  function MockFilePreviewContent(
    props: Parameters<typeof ActualFilePreviewContent>[0]
  ) {
    if (mockRenderActualResources)
      return <ActualFilePreviewContent {...props} />;
    const { filePath, revision, isActive, onRefreshingChange, refreshKey } =
      props;
    mockPreviewRender(filePath);
    if (onRefreshingChange)
      mockPreviewLoadingCallbacks.set(filePath, onRefreshingChange);
    return (
      <>
        <iframe
          title={filePath}
          data-testid={filePath}
          data-revision={revision}
          data-active={isActive}
          data-refresh={refreshKey}
        />
        <button
          data-testid={`start:${filePath}`}
          onClick={() => onRefreshingChange?.(true)}
        >
          Start file read
        </button>
        <button
          data-testid={`finish:${filePath}`}
          onClick={() => onRefreshingChange?.(false)}
        >
          Finish file read
        </button>
      </>
    );
  }
  return { FilePreviewContent: MockFilePreviewContent };
});

const store = () => useBuildSessionStore.getState();
const sessionId: string = "retained-tabs";
function openFile(path: string) {
  act(() =>
    store().openFilePreview(sessionId, path, path.split("/").pop() ?? path)
  );
}

const runningSandbox = {
  id: "sandbox",
  status: "running" as const,
  container_id: null,
  created_at: "2026-10-09T00:00:00Z",
  last_heartbeat: null,
};

beforeEach(() => {
  mockRenderActualResources = false;
  jest.mocked(fetchOutputCards).mockResolvedValue([]);
  jest
    .mocked(fetchDirectoryListing)
    .mockResolvedValue({ path: "", entries: [] });
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    preProvisioning: { status: "idle" },
    noSessionOutputPanelMode: "closed",
    noSessionOutputPanelInitialized: false,
    noSessionPanelTabs: [],
    noSessionActivePanelTabId: null,
  });
  store().createSession(sessionId, {
    status: "running",
    sandbox: runningSandbox,
  });
  store().setCurrentSession(sessionId);
  store().openFilesTab(sessionId);
});

// Resource lifecycle and toolbar callbacks

it("clears all collection filters when opening the same turn again", () => {
  mockRenderActualResources = true;
  store().openOutputsTab(sessionId, 0);
  store().updateOutputsTabState(sessionId, {
    searchQuery: "hidden",
    folder: "reports",
    fileType: "extension:pdf",
  });
  render(<BuildOutputPanel panelMode="medium" />);
  expect(screen.getByPlaceholderText("Search outputs")).toHaveValue("hidden");
  act(() => store().openOutputsTab(sessionId, 0));
  expect(screen.getByPlaceholderText("Search outputs")).toHaveValue("");
  expect(store().sessions.get(sessionId)?.outputsTabState).toEqual({
    turnIndex: 0,
    searchQuery: "",
    folder: "",
    fileType: "all",
  });
});

it("clears only the turn filter from the colored Outputs pill", async () => {
  mockRenderActualResources = true;
  store().openOutputsTab(sessionId, 3);
  store().updateOutputsTabState(sessionId, {
    searchQuery: "report",
    folder: "reports",
    fileType: "extension:pdf",
  });
  render(<BuildOutputPanel panelMode="medium" />);
  expect(
    screen.getByText("Turn 4 outputs").closest("[data-color]")
  ).toHaveAttribute("data-color", "blue");
  fireEvent.click(
    screen.getByRole("button", { name: "Remove Turn 4 outputs" })
  );
  expect(screen.queryByText("Turn 4 outputs")).not.toBeInTheDocument();
  expect(store().sessions.get(sessionId)?.outputsTabState).toEqual({
    turnIndex: null,
    searchQuery: "report",
    folder: "reports",
    fileType: "extension:pdf",
  });
  await act(async () => {});
});

it.each([false, true])(
  "disables reload while a Files read is pending (welcome: %s)",
  async (isWelcome) => {
    if (isWelcome) {
      useBuildSessionStore.setState({
        currentSessionId: null,
        preProvisioning: { status: "ready", sessionId },
      });
    }
    if (isWelcome) act(() => store().openFilesTab(null));
    render(<BuildOutputPanel panelMode="medium" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Start folder read" })
    );
    const refresh = screen.getByRole("button", {
      name: "Refresh",
    });
    expect(refresh).toHaveAttribute("aria-busy", "true");
    expect(refresh).toHaveAttribute("data-user-refreshing", "false");
    expect(refresh).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Finish folder read" }));
    fireEvent.click(refresh);
    expect(refresh).toHaveAttribute("data-user-refreshing", "true");
    expect(refresh).toHaveAttribute("aria-busy", "true");
    expect(refresh).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Finish folder read" }));
    expect(refresh).toHaveAttribute("aria-busy", "false");
    expect(refresh).toHaveAttribute("data-user-refreshing", "false");
    expect(refresh).toBeEnabled();
  }
);

it("keeps PDF and Files bodies mounted across resource switches", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  const files: HTMLElement = await screen.findByTestId("files-body");
  openFile("outputs/report.pdf");
  const pdf: HTMLElement = await screen.findByTestId("outputs/report.pdf");
  act(() => store().openFilesTab(sessionId));

  expect(pdf).toBeInTheDocument();
  expect(pdf.parentElement).toHaveAttribute("inert");
  expect(pdf.parentElement).toHaveAttribute("aria-hidden", "true");
  openFile("outputs/report.pdf");
  expect(screen.getByTestId("outputs/report.pdf")).toBe(pdf);
  expect(pdf.parentElement).not.toHaveAttribute("inert");

  expect(screen.getByTestId("files-body")).toBe(files);
});

it("does not render untouched retained previews when switching other tabs", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  for (const name of ["first", "middle", "last"]) {
    openFile(`outputs/${name}.md`);
    await screen.findByTestId(`outputs/${name}.md`);
  }
  mockPreviewRender.mockClear();
  openFile("outputs/first.md");
  expect(mockPreviewRender).not.toHaveBeenCalledWith("outputs/middle.md");
  expect(mockPreviewRender).toHaveBeenCalledWith("outputs/first.md");
});

it("keeps user reload indicators independent across file tabs", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  openFile("outputs/first.md");
  await screen.findByTestId("outputs/first.md");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  openFile("outputs/second.md");
  await screen.findByTestId("outputs/second.md");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  openFile("outputs/first.md");
  const reload = screen.getByRole("button", { name: "Refresh" });
  expect(reload).toHaveAttribute("data-user-refreshing", "true");
  fireEvent.click(screen.getByTestId("finish:outputs/second.md"));
  expect(reload).toHaveAttribute("data-user-refreshing", "true");
  fireEvent.click(screen.getByTestId("finish:outputs/first.md"));
  expect(reload).toHaveAttribute("data-user-refreshing", "false");
});

it("evicts the least recently visited tab at five, without reordering retained iframes", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  for (const name of ["a", "b", "c", "d", "e"]) {
    openFile(`outputs/${name}.txt`);
    await screen.findByTestId(`outputs/${name}.txt`);
  }
  const a: HTMLElement = screen.getByTestId("outputs/a.txt");
  const order: Element[] = Array.from(a.parentElement!.parentElement!.children);
  openFile("outputs/a.txt");
  expect(Array.from(a.parentElement!.parentElement!.children)).toEqual(order);
  openFile("outputs/f.txt");
  await screen.findByTestId("outputs/f.txt");
  expect(screen.getByTestId("outputs/a.txt")).toBe(a);
  expect(screen.queryByTestId("outputs/b.txt")).not.toBeInTheDocument();
  expect(document.querySelectorAll("iframe")).toHaveLength(5);
});

it("includes PDFs in the bounded file-viewer budget", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  for (const name of ["a", "b", "c", "d", "e"]) {
    openFile(`outputs/${name}.txt`);
    await screen.findByTestId(`outputs/${name}.txt`);
  }
  const oldest = screen.getByTestId("outputs/a.txt");
  openFile("outputs/report.pdf");
  const pdf = await screen.findByTestId("outputs/report.pdf");
  expect(oldest).not.toBeInTheDocument();
  expect(document.querySelectorAll("iframe")).toHaveLength(5);
  openFile("outputs/f.txt");
  await screen.findByTestId("outputs/f.txt");
  expect(oldest).not.toBeInTheDocument();
  expect(pdf).toBeInTheDocument();
  expect(document.querySelectorAll("iframe")).toHaveLength(5);
});

it("releases closed tabs and resets retained content when changing sessions", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  openFile("outputs/report.pdf");
  const original: HTMLElement = await screen.findByTestId("outputs/report.pdf");
  act(() => store().openFilesTab(sessionId));
  act(() => store().closePanelTab(sessionId, "file:outputs/report.pdf"));
  expect(original).not.toBeInTheDocument();
  openFile("outputs/report.pdf");
  const reopened: HTMLElement = await screen.findByTestId("outputs/report.pdf");
  expect(reopened).not.toBe(original);
  act(() => {
    store().createSession("other-session", { status: "running" });
    store().setCurrentSession("other-session");
  });
  expect(reopened).not.toBeInTheDocument();
});

it("retains inert viewers across close, open, and full transitions", async () => {
  const { rerender } = render(<BuildOutputPanel panelMode="medium" />);
  openFile("outputs/report.pdf");
  const pdf: HTMLElement = await screen.findByTestId("outputs/report.pdf");
  jest.useFakeTimers();
  try {
    rerender(<BuildOutputPanel panelMode="closed" />);
    expect(pdf).toBeInTheDocument();
    expect(pdf.parentElement).toHaveAttribute("inert");
    await act(async () => jest.advanceTimersByTimeAsync(300));
    expect(pdf).toBeInTheDocument();
    rerender(<BuildOutputPanel panelMode="full" />);
    expect(await screen.findByTestId("outputs/report.pdf")).toBe(pdf);
  } finally {
    jest.useRealTimers();
  }
});

it("closes an inactive file tab without selecting it or nesting buttons", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  openFile("outputs/first.pdf");
  openFile("outputs/second.pdf");
  await screen.findByTestId("outputs/second.pdf");
  const close = screen.getByRole("button", { name: "Close first.pdf" });
  expect(close.parentElement?.closest("button")).toBeNull();
  fireEvent.click(close);
  expect(store().sessions.get(sessionId)?.activePanelTabId).toBe(
    "file:outputs/second.pdf"
  );
  expect(screen.queryByTestId("outputs/first.pdf")).not.toBeInTheDocument();
});

it("keeps pending refresh state scoped to its resource while selection changes", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  openFile("outputs/first.pdf");
  await screen.findByTestId("outputs/first.pdf");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();

  openFile("outputs/second.pdf");
  await screen.findByTestId("outputs/second.pdf");
  const refresh = screen.getByRole("button", { name: "Refresh" });
  expect(refresh).toBeEnabled();
  fireEvent.click(screen.getByTestId("start:outputs/second.pdf"));
  expect(refresh).toBeDisabled();

  fireEvent.click(screen.getByTestId("finish:outputs/first.pdf"));
  expect(refresh).toBeDisabled();
  expect(store().sessions.get(sessionId)?.activePanelTabId).toBe(
    "file:outputs/second.pdf"
  );
  fireEvent.click(screen.getByTestId("finish:outputs/second.pdf"));
  expect(refresh).toBeEnabled();
  expect(screen.getByTestId("outputs/first.pdf")).toHaveAttribute(
    "data-refresh",
    "1"
  );
  expect(screen.getByTestId("outputs/second.pdf")).toHaveAttribute(
    "data-refresh",
    "0"
  );
});

it("polls a starting session after leaving a ready session with the same refresh counter", async () => {
  jest.useFakeTimers();
  let secondSessionReady = false;
  jest.mocked(fetchWebappInfo).mockImplementation(async (id) => ({
    has_webapp: true,
    webapp_url: `/api/build/sessions/${id}/webapp`,
    status: "active",
    ready: id === sessionId || secondSessionReady,
    sharing_scope: "private",
  }));
  store().updateSessionData(sessionId, { webappNeedsRefresh: 1 });
  store().createSession("starting-session", {
    status: "running",
    sandbox: runningSandbox,
    webappNeedsRefresh: 1,
    outputPanelMode: "medium",
  });
  store().openBrowserTab("starting-session", "starting-session");
  store().openBrowserTab(sessionId, sessionId);
  const { unmount } = render(<BuildOutputPanel panelMode="medium" />);
  try {
    await act(async () => jest.advanceTimersByTimeAsync(300));
    expect(
      screen.getByTitle(
        (title, element) =>
          title === "Preview Your App" && element?.tagName === "IFRAME"
      )
    ).toHaveAttribute("src", `/api/build/sessions/${sessionId}/webapp`);

    await act(async () => store().setCurrentSession("starting-session"));
    expect(document.querySelector("iframe")).toBeNull();
    secondSessionReady = true;
    await act(async () => jest.advanceTimersByTimeAsync(5100));
    expect(
      screen.getByTitle(
        (title, element) =>
          title === "Preview Your App" && element?.tagName === "IFRAME"
      )
    ).toHaveAttribute("src", "/api/build/sessions/starting-session/webapp");
    const requests = jest.mocked(fetchWebappInfo).mock.calls.length;
    await act(async () => jest.advanceTimersByTimeAsync(6000));
    expect(jest.mocked(fetchWebappInfo).mock.calls.length).toBeGreaterThan(
      requests
    );
  } finally {
    unmount();
    jest.useRealTimers();
    jest.mocked(fetchWebappInfo).mockResolvedValue({
      has_webapp: false,
      webapp_url: null,
      status: "active",
      ready: false,
      sharing_scope: "private",
    });
  }
});

it("keeps the serving preview until its replacement is ready", async () => {
  jest.useFakeTimers();
  let info: Awaited<ReturnType<typeof fetchWebappInfo>> = {
    has_webapp: true,
    ready: true,
    webapp_url: "/original-webapp",
    status: "active",
    sharing_scope: "private",
  };
  jest.mocked(fetchWebappInfo).mockImplementation(async () => info);
  store().openBrowserTab(sessionId, sessionId);
  const { unmount } = render(<BuildOutputPanel panelMode="medium" />);
  try {
    await act(async () => jest.advanceTimersByTimeAsync(300));
    const frame = screen.getByTitle(
      (title, element) =>
        title === "Preview Your App" && element?.tagName === "IFRAME"
    );
    expect(frame).toHaveAttribute("src", "/original-webapp");

    info = { ...info, ready: false, webapp_url: "/replacement-webapp" };
    await act(async () => {
      store().updateSessionData(sessionId, { webappNeedsRefresh: 1 });
    });
    expect(frame).toHaveAttribute("src", "/original-webapp");

    info = { ...info, ready: true };
    await act(async () => jest.advanceTimersByTimeAsync(5100));
    const replacement = screen.getByTitle(
      (title, element) =>
        title === "Preview Your App" && element?.tagName === "IFRAME"
    );
    expect(replacement).not.toBe(frame);
    expect(replacement).toHaveAttribute("src", "/replacement-webapp");
    expect(replacement).toHaveAttribute("inert");
    fireEvent.load(replacement);
    expect(replacement).not.toHaveAttribute("inert");

    await act(async () => {
      store().updateSessionData(sessionId, { webappNeedsRefresh: 2 });
    });
    const requests = jest.mocked(fetchWebappInfo).mock.calls.length;
    await act(async () => jest.advanceTimersByTimeAsync(6000));
    expect(jest.mocked(fetchWebappInfo).mock.calls.length).toBeGreaterThan(
      requests
    );
  } finally {
    unmount();
    jest.useRealTimers();
    jest.mocked(fetchWebappInfo).mockResolvedValue({
      has_webapp: false,
      webapp_url: null,
      status: "active",
      ready: false,
      sharing_scope: "private",
    });
  }
});

it("releases file refresh state when a tab closes", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  openFile("outputs/report.pdf");
  await screen.findByTestId("outputs/report.pdf");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  act(() => store().closePanelTab(sessionId, "file:outputs/report.pdf"));
  openFile("outputs/report.pdf");
  expect(await screen.findByTestId("outputs/report.pdf")).toHaveAttribute(
    "data-refresh",
    "0"
  );
  expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();
});

it("replaces a viewer when its file tab closes and reopens in one update", async () => {
  render(<BuildOutputPanel panelMode="medium" />);
  const path = "outputs/report.pdf";
  openFile(path);
  const original = await screen.findByTestId(path);
  const oldCompletion = mockPreviewLoadingCallbacks.get(path);
  expect(oldCompletion).toBeDefined();
  act(() => {
    store().closePanelTab(sessionId, `file:${path}`);
    store().openFilePreview(sessionId, path, "report.pdf");
  });
  const replacement = await screen.findByTestId(path);
  expect(replacement).not.toBe(original);
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  const reload = screen.getByRole("button", { name: "Refresh" });
  expect(reload).toBeDisabled();
  act(() => oldCompletion?.(false));
  expect(reload).toBeDisabled();
  expect(reload).toHaveAttribute("data-user-refreshing", "true");
  fireEvent.click(screen.getByTestId(`finish:${path}`));
  expect(reload).toBeEnabled();
});

it("accepts a pending viewer completion after the welcome workspace is claimed", async () => {
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    preProvisioning: { status: "ready", sessionId },
  });
  store().createSession(sessionId, { sandbox: runningSandbox });
  const path = "outputs/report.pdf";
  act(() => store().openFilePreview(null, path, "report.pdf"));
  render(<BuildOutputPanel panelMode="medium" />);
  const original = await screen.findByTestId(path);
  const welcomeCompletion = mockPreviewLoadingCallbacks.get(path);
  expect(welcomeCompletion).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  act(() => store().setCurrentSession(sessionId));
  expect(screen.getByTestId(path)).toBe(original);
  const reload = screen.getByRole("button", { name: "Refresh" });
  expect(reload).toBeDisabled();
  act(() => welcomeCompletion?.(false));
  expect(reload).toBeEnabled();
  expect(reload).toHaveAttribute("data-user-refreshing", "false");
});

it.each(["close", "switch"] as const)(
  "discards an export after its resource leaves (%s)",
  async (leave) => {
    jest.mocked(downloadFile).mockClear();
    let completeExport: (blob: Blob) => void = () => {
      throw new Error("Export not started");
    };
    jest.mocked(exportDocx).mockImplementationOnce(
      () =>
        new Promise<Blob>((resolve) => {
          completeExport = resolve;
        })
    );
    render(<BuildOutputPanel panelMode="medium" />);
    openFile("outputs/report.md");
    await screen.findByTestId("outputs/report.md");
    fireEvent.click(screen.getByRole("button", { name: "Export DOCX" }));
    act(() => {
      if (leave === "close") {
        store().closePanelTab(sessionId, "file:outputs/report.md");
        store().openFilePreview(sessionId, "outputs/report.md", "report.md");
      } else {
        store().createSession("other-session");
        store().setCurrentSession("other-session");
      }
    });
    await act(async () => completeExport(new Blob(["document"])));
    expect(downloadFile).not.toHaveBeenCalled();
  }
);

it("pauses directory reads until the sandbox has restored", () => {
  act(() =>
    store().updateSessionData(sessionId, {
      sandbox: {
        id: "sandbox",
        status: "restoring",
        container_id: null,
        created_at: "2026-10-09T00:00:00Z",
        last_heartbeat: null,
      },
    })
  );
  render(<BuildOutputPanel panelMode="medium" />);
  expect(screen.getByTestId("files-body")).toHaveAttribute(
    "data-active",
    "false"
  );
  act(() =>
    store().updateSessionData(sessionId, {
      sandbox: {
        id: "sandbox",
        status: "running",
        container_id: null,
        created_at: "2026-10-09T00:00:00Z",
        last_heartbeat: null,
      },
    })
  );
  expect(screen.getByTestId("files-body")).toHaveAttribute(
    "data-active",
    "true"
  );
});

it("defers previews during restore and reloads even an unchanged revision afterward", async () => {
  act(() =>
    store().openFilePreview(sessionId, "outputs/report.md", "report.md")
  );
  render(<BuildOutputPanel panelMode="medium" />);
  const preview = await screen.findByTestId("outputs/report.md");
  expect(preview).toHaveAttribute("data-active", "true");
  expect(preview).toHaveAttribute("data-refresh", "0");
  const sandbox = {
    id: "sandbox",
    container_id: null,
    created_at: "2026-10-09T00:00:00Z",
    last_heartbeat: null,
  };
  act(() =>
    store().updateSessionData(sessionId, {
      sandbox: { ...sandbox, status: "restoring" },
    })
  );
  expect(preview).toHaveAttribute("data-active", "false");
  act(() =>
    store().updateSessionData(sessionId, {
      sandbox: { ...sandbox, status: "running" },
      webappNeedsRemount: 1,
    })
  );
  expect(preview).toHaveAttribute("data-active", "true");
  expect(preview).toHaveAttribute("data-refresh", "1");
});

// Files integration and welcome-session handoff

describe("Files integration", () => {
  beforeEach(() => {
    mockRenderActualResources = true;
  });
  it("keeps the manual reload spinner until every directory read finishes", async () => {
    const rootListing = {
      path: "",
      entries: [
        {
          name: "outputs",
          path: "outputs",
          is_directory: true,
          size: null,
          mime_type: null,
        },
      ],
    };
    const childListing = { path: "outputs", entries: [] };
    jest
      .mocked(fetchDirectoryListing)
      .mockImplementation(async (_id, path) =>
        path === "outputs" ? childListing : rootListing
      );
    render(<BuildOutputPanel panelMode="medium" />);
    const reload = screen.getByRole("button", { name: "Refresh files" });
    await waitFor(() => expect(fetchDirectoryListing).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(reload).toBeEnabled());
    const root = deferred<Awaited<ReturnType<typeof fetchDirectoryListing>>>();
    const child = deferred<Awaited<ReturnType<typeof fetchDirectoryListing>>>();
    jest
      .mocked(fetchDirectoryListing)
      .mockImplementation((_id, path) =>
        path === "outputs" ? child.promise : root.promise
      );
    fireEvent.click(reload);
    await waitFor(() => expect(fetchDirectoryListing).toHaveBeenCalledTimes(4));
    expect(reload.querySelector(".motion-safe\\:animate-spin")).not.toBeNull();
    await act(async () => child.resolve(childListing));
    expect(reload).toBeDisabled();
    expect(reload.querySelector(".motion-safe\\:animate-spin")).not.toBeNull();
    await act(async () => root.resolve(rootListing));
    await waitFor(() => expect(reload).toBeEnabled());
    expect(reload.querySelector(".motion-safe\\:animate-spin")).toBeNull();
  });

  it("warms directories after readiness and keeps an in-flight read through tab closure", async () => {
    store().updateSessionData(sessionId, {
      sandbox: null,
      panelTabs: [],
      activePanelTabId: null,
    });
    const pending =
      deferred<Awaited<ReturnType<typeof fetchDirectoryListing>>>();
    jest.mocked(fetchDirectoryListing).mockImplementation((_sessionId, path) =>
      path === "outputs"
        ? pending.promise
        : Promise.resolve({
            path: "",
            entries: [
              {
                name: "outputs",
                path: "outputs",
                is_directory: true,
                size: null,
                mime_type: null,
              },
            ],
          })
    );
    const { rerender } = render(<BuildOutputPanel panelMode="closed" />);
    expect(fetchDirectoryListing).not.toHaveBeenCalled();
    act(() =>
      store().updateSessionData(sessionId, { sandbox: runningSandbox })
    );
    await waitFor(() => expect(fetchDirectoryListing).toHaveBeenCalledTimes(2));
    const signal = jest.mocked(fetchDirectoryListing).mock.calls[1]?.[2];
    act(() => store().openFilesTab(sessionId));
    rerender(<BuildOutputPanel panelMode="medium" />);
    act(() => store().closePanelTab(sessionId, "files"));
    act(() => store().openFilesTab(sessionId));
    expect(signal?.aborted).toBe(false);
    expect(fetchDirectoryListing).toHaveBeenCalledTimes(2);
    await act(async () =>
      pending.resolve({
        path: "outputs",
        entries: [
          {
            name: "ready.txt",
            path: "outputs/ready.txt",
            is_directory: false,
            size: 5,
            mime_type: "text/plain",
          },
        ],
      })
    );
    expect(
      await screen.findByRole("button", { name: "ready.txt" })
    ).toBeVisible();
    expect(fetchDirectoryListing).toHaveBeenCalledTimes(2);
  });

  it.each([false, true])(
    "reloads a welcome file tab and releases the toolbar (after handoff: %s)",
    async (afterHandoff) => {
      const sessionId = `inline-refresh-${afterHandoff}`;
      const store = () => useBuildSessionStore.getState();
      useBuildSessionStore.setState({
        currentSessionId: null,
        sessions: new Map(),
        preProvisioning: { status: "ready", sessionId },
        noSessionOutputPanelMode: "closed",
        noSessionOutputPanelInitialized: false,
        noSessionPanelTabs: [],
        noSessionActivePanelTabId: null,
      });
      store().createSession(sessionId, { sandbox: runningSandbox });
      act(() => store().openFilesTab(null));
      jest.mocked(fetchDirectoryListing).mockResolvedValue({
        path: "",
        entries: [
          {
            name: "notes.txt",
            path: "outputs/notes.txt",
            is_directory: false,
            size: 10,
            mime_type: "text/plain",
          },
        ],
      });
      jest.mocked(fetchFileContent).mockResolvedValue({
        content: "Before refresh",
        isImage: false,
        mimeType: "text/plain",
      });
      render(<BuildOutputPanel panelMode="medium" />);
      fireEvent.click(await screen.findByRole("button", { name: /notes.txt/ }));
      expect(await screen.findByText("Before refresh")).toBeInTheDocument();
      if (afterHandoff) act(() => store().setCurrentSession(sessionId));
      jest.mocked(fetchFileContent).mockResolvedValue({
        content: "After refresh",
        isImage: false,
        mimeType: "text/plain",
      });
      const readsBefore = jest.mocked(fetchFileContent).mock.calls.length;
      await act(async () => store().triggerFilesRefresh(sessionId));
      expect(fetchFileContent).toHaveBeenCalledTimes(readsBefore);
      expect(screen.getByText("Before refresh")).toBeInTheDocument();
      const refresh = screen.getByRole("button", { name: "Reload file" });
      fireEvent.click(refresh);
      expect(await screen.findByText("After refresh")).toBeInTheDocument();
      expect(refresh).toBeEnabled();
      expect(refresh).toHaveAttribute("aria-busy", "false");
    }
  );

  it("preserves welcome Outputs filters through provisioning and claim", async () => {
    const store = () => useBuildSessionStore.getState();
    useBuildSessionStore.setState({
      sessions: new Map(),
      preProvisioning: { status: "idle" },
    });
    store().setCurrentSession(null);
    store().openOutputsTab(null);
    render(<BuildOutputPanel panelMode="medium" />);
    const search = screen.getByRole("textbox", { name: "Search outputs" });
    fireEvent.change(search, { target: { value: "notes" } });
    act(() => {
      store().createSession("provisioned");
      useBuildSessionStore.setState({
        preProvisioning: { status: "ready", sessionId: "provisioned" },
      });
    });
    expect(search).toHaveValue("notes");
    act(() =>
      store().updateOutputsTabState("provisioned", {
        folder: "reports",
        fileType: "extension:md",
      })
    );
    act(() => {
      useBuildSessionStore.setState({
        preProvisioning: { status: "starting", sessionId: "provisioned" },
      });
      store().createSession("provisioned");
      store().setCurrentSession("provisioned");
    });
    expect(search).toHaveValue("notes");
    expect(store().sessions.get("provisioned")?.outputsTabState).toEqual({
      searchQuery: "notes",
      folder: "reports",
      fileType: "extension:md",
      turnIndex: null,
    });
    act(() => {
      store().createSession("saved");
      store().updateOutputsTabState("saved", { searchQuery: "saved query" });
      store().setCurrentSession("saved");
      store().openOutputsTab("saved");
      store().updateOutputsTabState("saved", { searchQuery: "saved query" });
    });
    expect(screen.getByRole("textbox", { name: "Search outputs" })).toHaveValue(
      "saved query"
    );
    act(() => {
      store().setCurrentSession(null);
      store().openOutputsTab(null);
    });
    expect(screen.getByRole("textbox", { name: "Search outputs" })).toHaveValue(
      ""
    );
    expect(store().sessions.get("saved")?.outputsTabState.searchQuery).toBe(
      "saved query"
    );
    await act(async () => {});
  });

  it("preserves welcome search through provisioning and claim, and clears it for another session", async () => {
    const store = () => useBuildSessionStore.getState();
    useBuildSessionStore.setState({
      sessions: new Map(),
      preProvisioning: { status: "idle" },
    });
    store().setCurrentSession(null);
    store().openFilesTab(null);
    jest
      .mocked(fetchDirectoryListing)
      .mockResolvedValue({ path: "", entries: [] });
    render(<BuildOutputPanel panelMode="medium" />);
    const search = screen.getByRole("textbox", { name: "Search files" });
    fireEvent.change(search, { target: { value: "notes" } });
    act(() => {
      store().createSession("provisioned");
      useBuildSessionStore.setState({
        preProvisioning: { status: "ready", sessionId: "provisioned" },
      });
    });
    expect(screen.getByRole("textbox", { name: "Search files" })).toBe(search);
    expect(search).toHaveValue("notes");
    act(() => store().setCurrentSession("provisioned"));
    expect(screen.getByRole("textbox", { name: "Search files" })).toBe(search);
    expect(search).toHaveValue("notes");
    act(() => {
      store().createSession("unrelated");
      store().setCurrentSession("unrelated");
      store().openFilesTab("unrelated");
    });
    expect(screen.getByRole("textbox", { name: "Search files" })).toHaveValue(
      ""
    );
    await act(async () => {});
  });
});

// Inventory revisions with actual PowerPoint and PDF viewers

jest.mock("@/app/craft/components/output-panel/PdfDocumentViewer", () => ({
  __esModule: true,
  default: jest.fn(({ blob }: { blob: Blob }) => (
    <div title="report.pdf" data-size={blob.size} />
  )),
}));

describe("Inventory revision integration", () => {
  const sessionId = "preview-inventory";
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;
  const originalScrollIntoView = Element.prototype.scrollIntoView;

  async function refreshInventory(files: OutputInventory["files"]) {
    jest.mocked(fetchOutputInventory).mockResolvedValue({
      files,
      complete: true,
    });
    await act(async () => store().refreshOutputInventory(sessionId));
  }

  beforeEach(() => {
    mockRenderActualResources = true;
    jest.clearAllMocks();
    let nextObjectUrl = 0;
    URL.createObjectURL = jest.fn(() => `blob:preview-${++nextObjectUrl}`);
    URL.revokeObjectURL = jest.fn();
    Element.prototype.scrollIntoView = jest.fn();
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
      preProvisioning: { status: "idle" },
      noSessionOutputPanelMode: "closed",
      noSessionOutputPanelInitialized: false,
      noSessionPanelTabs: [],
      noSessionActivePanelTabId: null,
    });
    store().createSession(sessionId, {
      status: "running",
      sandbox: runningSandbox,
    });
    store().setCurrentSession(sessionId);
  });

  afterEach(() => {
    cleanup();
    jest.useRealTimers();
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    Element.prototype.scrollIntoView = originalScrollIntoView;
    jest.restoreAllMocks();
  });

  it("refreshes an open PowerPoint through inventory updates and reuses unchanged conversions", async () => {
    const path = "outputs/deck.pptx";
    jest.mocked(fetchPptxPreview).mockResolvedValue({
      slide_count: 1,
      slide_paths: ["outputs/.pptx-preview/deck/slide-1.jpg"],
      cached: false,
    });
    await refreshInventory([{ path, revision: "100:1000", size: 1000 }]);
    expect(store().sessions.get(sessionId)).toMatchObject({
      outputPanelMode: "closed",
      panelTabs: [],
    });
    render(<BuildOutputPanel panelMode="medium" />);
    act(() => store().openFilePreview(sessionId, path, "deck.pptx"));
    const originalUrl = (
      await screen.findByAltText("Slide 1 of 1")
    ).getAttribute("src");
    expect(fetchPptxPreview).toHaveBeenCalledTimes(1);
    expect(fetchPptxPreview).toHaveBeenLastCalledWith(sessionId, path);

    await refreshInventory([{ path, revision: "200:1000", size: 1000 }]);
    await waitFor(() => expect(fetchPptxPreview).toHaveBeenCalledTimes(2));
    const updatedImage = await screen.findByAltText("Slide 1 of 1");
    const updatedUrl = updatedImage.getAttribute("src");
    expect(updatedUrl).not.toBe(originalUrl);
    expect(updatedImage).toHaveAttribute("alt", "Slide 1 of 1");

    act(() => store().openFilesTab(sessionId));
    act(() => store().setActivePanelTabId(sessionId, `file:${path}`));
    expect(screen.getByAltText("Slide 1 of 1")).toBe(updatedImage);
    expect(fetchPptxPreview).toHaveBeenCalledTimes(2);

    act(() => store().closePanelTab(sessionId, `file:${path}`));
    expect(screen.queryByAltText("Slide 1 of 1")).not.toBeInTheDocument();
    act(() => store().openFilePreview(sessionId, path, "deck.pptx"));
    expect(await screen.findByAltText("Slide 1 of 1")).not.toHaveAttribute(
      "src",
      updatedUrl
    );
    expect(fetchPptxPreview).toHaveBeenCalledTimes(3);
  });

  it("refreshes an open PDF through inventory updates and reuses unchanged bytes", async () => {
    const path = "outputs/report.pdf";
    const fetch = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("original PDF bytes"))
      .mockImplementation(async () => new Response("updated PDF bytes"));
    await refreshInventory([{ path, revision: "100:1000", size: 1000 }]);
    expect(store().sessions.get(sessionId)).toMatchObject({
      outputPanelMode: "closed",
      panelTabs: [],
    });
    render(<BuildOutputPanel panelMode="medium" />);
    act(() => store().openFilePreview(sessionId, path, "report.pdf"));
    await screen.findByTitle("report.pdf");
    const displayed = () =>
      jest.mocked(PdfDocumentViewer).mock.calls.at(-1)?.[0].blob;
    const originalBlob = displayed();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenLastCalledWith(
      `/api/build/sessions/${sessionId}/artifacts/outputs/report.pdf`,
      { cache: "no-store" }
    );

    await refreshInventory([{ path, revision: "200:1000", size: 1000 }]);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(displayed()).not.toBe(originalBlob));
    const updatedFrame = screen.getByTitle("report.pdf");
    const updatedBlob = displayed();
    act(() => store().openFilesTab(sessionId));
    act(() => store().setActivePanelTabId(sessionId, `file:${path}`));
    expect(screen.getByTitle("report.pdf")).toBe(updatedFrame);
    expect(fetch).toHaveBeenCalledTimes(2);

    act(() => store().closePanelTab(sessionId, `file:${path}`));
    expect(screen.queryByTitle("report.pdf")).not.toBeInTheDocument();
    act(() => store().openFilePreview(sessionId, path, "report.pdf"));
    await screen.findByTitle("report.pdf");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(displayed()).not.toBe(updatedBlob);
  });
});

// Sandbox discovery
it("defers file reads during sandbox discovery", () => {
  store().updateSessionData(sessionId, { sandbox: null, isLoaded: true });
  render(<BuildOutputPanel panelMode="medium" />);
  expect(screen.getByTestId("files-body")).toHaveAttribute(
    "data-active",
    "false"
  );
  act(() => store().updateSessionData(sessionId, { sandbox: runningSandbox }));
  expect(screen.getByTestId("files-body")).toHaveAttribute(
    "data-active",
    "true"
  );
});

// Outputs resource integration
it("opens output cards as file tabs and keeps All Files available", async () => {
  const path = "outputs/report.md";
  jest.mocked(fetchOutputInventory).mockResolvedValue({
    complete: true,
    files: [{ path, size: 12, revision: "one" }],
  });
  store().updateSessionData(sessionId, { status: "active" });
  store().openOutputsTab(sessionId);
  await store().refreshOutputInventory(sessionId, { silent: true });
  render(<BuildOutputPanel panelMode="medium" />);
  const card = await screen.findByRole("button", { name: path });
  expect(screen.getByRole("tab", { name: "Outputs" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.getByRole("tab", { name: "All Files" })).toBeInTheDocument();
  expect(screen.getByTestId("resource-location")).toHaveTextContent(
    "Files created by your agent"
  );
  fireEvent.click(card);
  expect(screen.getByRole("tab", { name: "report.md" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(store().sessions.get(sessionId)?.activePanelTabId).toBe(
    `file:${path}`
  );
});

it.each(["active", "running"] as const)(
  "manual reload retains selection and discovers new task files (%s)",
  async (status) => {
    const path = "outputs/report.md";
    const inventory: OutputInventory = {
      complete: true,
      files: [{ path, size: 12, revision: "one" }],
    };
    jest.mocked(fetchOutputInventory).mockResolvedValue(inventory);
    store().updateSessionData(sessionId, { status: "active" });
    store().openOutputsTab(sessionId);
    await store().refreshOutputInventory(sessionId, { silent: true });
    render(<BuildOutputPanel panelMode="medium" />);
    await screen.findByRole("button", { name: path });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled()
    );
    store().updateSessionData(sessionId, { status });
    const newPath = "outputs/new.md";
    const refreshed = {
      ...inventory,
      files: [...inventory.files, { path: newPath, size: 8, revision: "two" }],
    };
    let finish = () => {};
    jest.mocked(fetchOutputInventory).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = () => resolve(refreshed);
        })
    );
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(screen.getByRole("button", { name: path })).toBeVisible();
    expect(screen.getByRole("button", { name: "Refresh" })).toHaveAttribute(
      "data-user-refreshing",
      "true"
    );
    await act(async () => finish());
    expect(screen.getByRole("button", { name: "Refresh" })).toHaveAttribute(
      "data-user-refreshing",
      "false"
    );
    expect(store().sessions.get(sessionId)?.activePanelTabId).toBe("outputs");
    expect(
      store()
        .sessions.get(sessionId)
        ?.panelTabs.some((tab) => tab.kind === "file" && tab.path === newPath)
    ).toBe(status === "running");
  }
);

it("keeps discovery polls separate from document reloads", async () => {
  const info = {
    has_webapp: true,
    ready: true,
    webapp_url: "/todo-app",
    status: "running",
    sharing_scope: "private" as const,
  };
  jest.mocked(fetchWebappInfo).mockResolvedValue(info);
  store().openBrowserTab(sessionId, sessionId);
  render(<BuildOutputPanel panelMode="medium" />);
  const frame = await screen.findByTitle(
    (title, element) =>
      title === "Preview Your App" && element?.tagName === "IFRAME"
  );
  const refresh = screen.getByRole("button", { name: "Refresh" });
  expect(refresh).toBeDisabled();
  fireEvent.load(frame);
  expect(refresh).toBeEnabled();
  const poll = deferred<Awaited<ReturnType<typeof fetchWebappInfo>>>();
  const requests = jest.mocked(fetchWebappInfo).mock.calls.length;
  jest.mocked(fetchWebappInfo).mockReturnValue(poll.promise);
  act(() => store().updateSessionData(sessionId, { webappNeedsRefresh: 1 }));
  await waitFor(() =>
    expect(jest.mocked(fetchWebappInfo).mock.calls.length).toBeGreaterThan(
      requests
    )
  );
  expect(refresh).toBeEnabled();
  fireEvent.click(refresh);
  const replacement = screen.getByTitle(
    (title, element) =>
      title === "Preview Your App" && element?.tagName === "IFRAME"
  );
  expect(replacement).not.toBe(frame);
  expect(refresh).toBeDisabled();
  expect(refresh).toHaveAttribute("data-user-refreshing", "true");
  fireEvent.load(replacement);
  expect(refresh).toBeEnabled();
  expect(refresh).toHaveAttribute("data-user-refreshing", "false");
  await act(async () => poll.resolve(info));
});

// Original file downloads.
it.each([false, true])(
  "downloads the original CSV from a resource tab (welcome: %s)",
  async (welcome) => {
    mockRenderActualResources = true;
    if (welcome) {
      useBuildSessionStore.setState({
        currentSessionId: null,
        preProvisioning: { status: "ready", sessionId },
      });
    }
    store().openFilePreview(
      welcome ? null : sessionId,
      "outputs/data.csv",
      "data.csv"
    );
    jest.mocked(fetchFileContent).mockResolvedValue({
      content: "name,value\nAlice,42",
      isImage: false,
      mimeType: "text/csv",
    });
    render(<BuildOutputPanel panelMode="medium" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download file" })
    );
    expect(downloadArtifactFile).toHaveBeenCalledWith(
      sessionId,
      "outputs/data.csv"
    );
  }
);
