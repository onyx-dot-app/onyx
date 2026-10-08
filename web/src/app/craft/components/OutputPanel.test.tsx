import { act, fireEvent, render, screen } from "@tests/setup/test-utils";
import BuildOutputPanel from "@/app/craft/components/OutputPanel";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { fetchWebappInfo } from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchArtifacts: jest.fn().mockResolvedValue([]),
  fetchWebappInfo: jest
    .fn()
    .mockResolvedValue({ has_webapp: false, ready: false }),
}));
jest.mock("@/app/craft/components/output-panel/UrlBar", () => {
  function MockUrlBar({
    onRefresh,
    isRefreshing,
  }: {
    onRefresh: () => void;
    isRefreshing: boolean;
  }) {
    return (
      <button
        onClick={onRefresh}
        aria-busy={isRefreshing}
        disabled={isRefreshing}
      >
        Refresh
      </button>
    );
  }
  return { __esModule: true, default: MockUrlBar };
});
jest.mock("@/app/craft/components/output-panel/FilesTab", () => {
  function MockFilesTab({
    onRefreshingChange,
  }: {
    onRefreshingChange: (loading: boolean) => void;
  }) {
    return (
      <div data-testid="files-body">
        <button onClick={() => onRefreshingChange(true)}>
          Start folder read
        </button>
        <button onClick={() => onRefreshingChange(false)}>
          Finish folder read
        </button>
      </div>
    );
  }
  return { __esModule: true, default: MockFilesTab };
});
jest.mock("@/app/craft/components/output-panel/ArtifactsTab", () => {
  function MockArtifactsTab() {
    return <div data-testid="artifacts-body" />;
  }
  return { __esModule: true, default: MockArtifactsTab };
});
jest.mock("@/app/craft/components/output-panel/FilePreviewContent", () => {
  function MockFilePreviewContent({
    filePath,
    revision,
    isActive,
  }: {
    filePath: string;
    revision?: string;
    isActive?: boolean;
  }) {
    return (
      <iframe
        title={filePath}
        data-revision={revision}
        data-active={isActive}
      />
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

beforeEach(() => {
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    preProvisioning: { status: "idle" },
  });
  store().createSession(sessionId, { status: "running" });
  store().setCurrentSession(sessionId);
});

it.each([false, true])(
  "only animates explicit refreshes (welcome: %s)",
  async (isWelcome) => {
    if (isWelcome) {
      useBuildSessionStore.setState({
        currentSessionId: null,
        preProvisioning: { status: "ready", sessionId },
      });
    }
    render(<BuildOutputPanel isOpen />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Start folder read" })
    );
    const refresh = screen.getByRole("button", {
      name: "Refresh",
    });
    expect(refresh).toHaveAttribute("aria-busy", "false");
    expect(refresh).toBeEnabled();

    fireEvent.click(refresh);
    expect(refresh).toHaveAttribute("aria-busy", "true");
    expect(refresh).toBeDisabled();
    expect(store().sessions.get(sessionId)?.filesNeedsRefresh).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Finish folder read" }));
    expect(refresh).toHaveAttribute("aria-busy", "false");
    expect(refresh).toBeEnabled();
  }
);

it("keeps PDF and pinned tab bodies mounted across switches", async () => {
  render(<BuildOutputPanel isOpen />);
  const files: HTMLElement = await screen.findByTestId("files-body");
  openFile("outputs/report.pdf");
  const pdf: HTMLElement = await screen.findByTitle("outputs/report.pdf");
  fireEvent.click(screen.getByRole("button", { name: "Artifacts" }));
  const artifacts: HTMLElement = await screen.findByTestId("artifacts-body");
  expect(pdf).toBeInTheDocument();
  expect(pdf.parentElement).toHaveAttribute("inert");
  expect(pdf.parentElement).toHaveAttribute("aria-hidden", "true");
  openFile("outputs/report.pdf");
  expect(screen.getByTitle("outputs/report.pdf")).toBe(pdf);
  expect(pdf.parentElement).not.toHaveAttribute("inert");
  expect(screen.getByTestId("artifacts-body")).toBe(artifacts);
  expect(screen.getByTestId("files-body")).toBe(files);
});

it("evicts the least recently visited tab at five, without reordering retained iframes", async () => {
  render(<BuildOutputPanel isOpen />);
  for (const name of ["a", "b", "c", "d", "e"]) {
    openFile(`outputs/${name}.pdf`);
    await screen.findByTitle(`outputs/${name}.pdf`);
  }
  const a: HTMLElement = screen.getByTitle("outputs/a.pdf");
  const order: Element[] = Array.from(a.parentElement!.parentElement!.children);
  openFile("outputs/a.pdf");
  expect(Array.from(a.parentElement!.parentElement!.children)).toEqual(order);
  openFile("outputs/f.pdf");
  await screen.findByTitle("outputs/f.pdf");
  expect(screen.getByTitle("outputs/a.pdf")).toBe(a);
  expect(screen.queryByTitle("outputs/b.pdf")).not.toBeInTheDocument();
  expect(document.querySelectorAll("iframe")).toHaveLength(5);
});

it("releases closed tabs and resets retained content when changing sessions", async () => {
  render(<BuildOutputPanel isOpen />);
  openFile("outputs/report.pdf");
  const original: HTMLElement = await screen.findByTitle("outputs/report.pdf");
  fireEvent.click(screen.getByRole("button", { name: "Artifacts" }));
  act(() => store().closePanelTab(sessionId, "file:outputs/report.pdf"));
  expect(original).not.toBeInTheDocument();
  openFile("outputs/report.pdf");
  const reopened: HTMLElement = await screen.findByTitle("outputs/report.pdf");
  expect(reopened).not.toBe(original);
  act(() => {
    store().createSession("other-session", { status: "running" });
    store().setCurrentSession("other-session");
  });
  expect(reopened).not.toBeInTheDocument();
});

it("releases retained viewers after the panel closes", async () => {
  const { rerender } = render(<BuildOutputPanel isOpen />);
  openFile("outputs/report.pdf");
  const pdf: HTMLElement = await screen.findByTitle("outputs/report.pdf");
  jest.useFakeTimers();
  try {
    rerender(<BuildOutputPanel isOpen={false} />);
    expect(pdf).toBeInTheDocument();
    expect(pdf.parentElement).toHaveAttribute("inert");
    await act(async () => jest.advanceTimersByTimeAsync(300));
    expect(pdf).not.toBeInTheDocument();
    rerender(<BuildOutputPanel isOpen />);
    expect(await screen.findByTitle("outputs/report.pdf")).not.toBe(pdf);
  } finally {
    jest.useRealTimers();
  }
});

it("closes an inactive file tab without selecting it or nesting buttons", async () => {
  render(<BuildOutputPanel isOpen />);
  openFile("outputs/first.pdf");
  openFile("outputs/second.pdf");
  await screen.findByTitle("outputs/second.pdf");
  const close = screen.getByRole("button", { name: "Close first.pdf" });
  expect(close.parentElement?.closest("button")).toBeNull();
  fireEvent.click(close);
  expect(store().sessions.get(sessionId)?.activePanelTabId).toBe(
    "file:outputs/second.pdf"
  );
  expect(screen.queryByTitle("outputs/first.pdf")).not.toBeInTheDocument();
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
    webappNeedsRefresh: 1,
    activeOutputTab: "preview",
  });
  store().setActiveOutputTab(sessionId, "preview");
  const { unmount } = render(<BuildOutputPanel isOpen />);
  try {
    await act(async () => jest.advanceTimersByTimeAsync(300));
    expect(screen.getByTitle("Web App Preview")).toHaveAttribute(
      "src",
      `/api/build/sessions/${sessionId}/webapp`
    );

    await act(async () => store().setCurrentSession("starting-session"));
    expect(screen.getByText("Starting the dev server...")).toBeInTheDocument();
    secondSessionReady = true;
    await act(async () => jest.advanceTimersByTimeAsync(2100));
    expect(screen.getByTitle("Web App Preview")).toHaveAttribute(
      "src",
      "/api/build/sessions/starting-session/webapp"
    );
    const requests = jest.mocked(fetchWebappInfo).mock.calls.length;
    await act(async () => jest.advanceTimersByTimeAsync(6000));
    expect(fetchWebappInfo).toHaveBeenCalledTimes(requests);
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

it("keeps the serving preview until its replacement is ready and stops polling afterward", async () => {
  jest.useFakeTimers();
  let info: Awaited<ReturnType<typeof fetchWebappInfo>> = {
    has_webapp: true,
    ready: true,
    webapp_url: "/original-webapp",
    status: "active",
    sharing_scope: "private",
  };
  jest.mocked(fetchWebappInfo).mockImplementation(async () => info);
  store().setActiveOutputTab(sessionId, "preview");
  const { unmount } = render(<BuildOutputPanel isOpen />);
  try {
    await act(async () => jest.advanceTimersByTimeAsync(300));
    const frame = screen.getByTitle("Web App Preview");
    expect(frame).toHaveAttribute("src", "/original-webapp");

    info = { ...info, ready: false, webapp_url: "/replacement-webapp" };
    await act(async () => {
      store().updateSessionData(sessionId, { webappNeedsRefresh: 1 });
    });
    expect(frame).toHaveAttribute("src", "/original-webapp");

    info = { ...info, ready: true };
    await act(async () => jest.advanceTimersByTimeAsync(2100));
    expect(screen.getByTitle("Web App Preview")).toBe(frame);
    expect(frame).toHaveAttribute("src", "/replacement-webapp");

    await act(async () => {
      store().updateSessionData(sessionId, { webappNeedsRefresh: 2 });
    });
    const requests = jest.mocked(fetchWebappInfo).mock.calls.length;
    await act(async () => jest.advanceTimersByTimeAsync(6000));
    expect(fetchWebappInfo).toHaveBeenCalledTimes(requests);
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
