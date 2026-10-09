import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import { SWRConfig } from "swr";

import FilesTab from "@/app/craft/components/output-panel/FilesTab";
import {
  useBuildSessionStore,
  usePreProvisionedSessionId,
  useSessionId,
} from "@/app/craft/hooks/useBuildSessionStore";
import {
  createSession,
  fetchDirectoryListing,
} from "@/app/craft/services/apiServices";
import type {
  DirectoryListing,
  FileSystemEntry,
} from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchDirectoryListing: jest.fn(),
  createSession: jest.fn(),
}));

jest.mock("@/app/craft/components/output-panel/FilePreviewContent", () => ({
  FilePreviewContent: ({ revision }: { revision?: string }) => (
    <div data-testid="inline-preview" data-revision={revision} />
  ),
}));

const mockedFetchDirectoryListing = jest.mocked(fetchDirectoryListing);

function file(name: string, path: string): FileSystemEntry {
  return {
    name,
    path,
    is_directory: false,
    size: 10,
    mime_type: "text/plain",
  };
}

const outputsDirectory: FileSystemEntry = {
  name: "outputs",
  path: "outputs",
  is_directory: true,
  size: null,
  mime_type: null,
};

function SessionFiles() {
  const currentSessionId = useSessionId();
  const preProvisionedSessionId = usePreProvisionedSessionId();
  const sessionId = currentSessionId ?? preProvisionedSessionId;
  return (
    <FilesTab
      key={sessionId}
      sessionId={sessionId}
      isPreProvisioned={!currentSessionId}
    />
  );
}

describe("FilesTab", () => {
  beforeEach(() => {
    mockedFetchDirectoryListing.mockReset();
    useBuildSessionStore.setState({
      currentSessionId: null,
      sessions: new Map(),
      preProvisioning: { status: "idle" },
      sessionHistory: [],
    });
  });

  it("keeps the same directory and expanded files throughout the first-message handoff", async () => {
    const sessionId = "welcome-session";
    jest.mocked(createSession).mockResolvedValue({
      id: sessionId,
      user_id: null,
      name: null,
      status: "active",
      created_at: "2026-10-07T00:00:00Z",
      last_activity_at: "2026-10-07T00:00:00Z",
      nextjs_port: null,
      sandbox: null,
      artifacts: [],
      sharing_scope: "private",
      origin: "INTERACTIVE",
      agent_provider: null,
      agent_model: null,
      skills_stale: false,
      session_loaded_in_sandbox: true,
    });
    mockedFetchDirectoryListing.mockImplementation((_sessionId, path) =>
      Promise.resolve({
        path: path ?? "",
        entries:
          path === "outputs"
            ? [file("notes.txt", "outputs/notes.txt")]
            : [outputsDirectory],
      })
    );
    const store = () => useBuildSessionStore.getState();
    await store().ensurePreProvisionedSession();
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <SessionFiles />
      </SWRConfig>
    );
    fireEvent.click(await screen.findByText("outputs"));
    const visibleFile = await screen.findByText("notes.txt");
    const listingRequests = mockedFetchDirectoryListing.mock.calls.length;

    await act(async () => {
      expect(await store().consumePreProvisionedSession()).toBe(sessionId);
    });
    expect(screen.getByText("notes.txt")).toBe(visibleFile);
    expect(await store().consumePreProvisionedSession()).toBeNull();
    expect(await store().ensurePreProvisionedSession()).toBeNull();

    act(() => store().createSession(sessionId, { status: "running" }));
    expect(screen.getByText("notes.txt")).toBe(visibleFile);

    act(() => store().setCurrentSession(sessionId));
    expect(screen.getByText("notes.txt")).toBe(visibleFile);
    expect(store().preProvisioning).toEqual({ status: "idle" });
    expect(mockedFetchDirectoryListing).toHaveBeenCalledTimes(listingRequests);
  });

  it("keeps visible children while refreshing and rejects superseded results", async () => {
    const sessionId = "refresh-race";
    const resolvers: Array<(listing: DirectoryListing) => void> = [];
    const signals: AbortSignal[] = [];
    mockedFetchDirectoryListing.mockImplementation(
      async (_id, path, signal) => {
        if (!path) return { path: "", entries: [outputsDirectory] };
        if (signal) signals.push(signal);
        return new Promise<DirectoryListing>((resolve) =>
          resolvers.push(resolve)
        );
      }
    );
    const store = () => useBuildSessionStore.getState();
    store().createSession(sessionId);
    render(<FilesTab sessionId={sessionId} />);
    fireEvent.click(await screen.findByRole("button", { name: "outputs" }));
    await waitFor(() => expect(resolvers).toHaveLength(1));
    await act(async () =>
      resolvers[0]?.({
        path: "outputs",
        entries: [file("old.txt", "outputs/old.txt")],
      })
    );
    act(() => store().triggerFilesRefresh(sessionId));
    await waitFor(() => expect(resolvers).toHaveLength(2));
    expect(screen.getByText("old.txt")).toBeInTheDocument();
    act(() => store().triggerFilesRefresh(sessionId));
    await waitFor(() => expect(resolvers).toHaveLength(3));
    expect(signals[1]?.aborted).toBe(true);
    await act(async () =>
      resolvers[2]?.({
        path: "outputs",
        entries: [file("new.txt", "outputs/new.txt")],
      })
    );
    await act(async () =>
      resolvers[1]?.({
        path: "outputs",
        entries: [file("stale.txt", "outputs/stale.txt")],
      })
    );
    expect(screen.getByText("new.txt")).toBeInTheDocument();
    expect(screen.queryByText("stale.txt")).not.toBeInTheDocument();
  });

  it("refreshes a previously empty folder when reopened", async () => {
    const sessionId = "reopen-empty";
    let entries: FileSystemEntry[] = [];
    mockedFetchDirectoryListing.mockImplementation(async (_id, path) => ({
      path: path ?? "",
      entries: path ? entries : [outputsDirectory],
    }));
    useBuildSessionStore.getState().createSession(sessionId);
    render(<FilesTab sessionId={sessionId} />);
    const folder = await screen.findByRole("button", { name: "outputs" });
    fireEvent.click(folder);
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument()
    );
    expect(
      screen.queryByText("No files in this directory")
    ).not.toBeInTheDocument();
    fireEvent.click(folder);
    entries = [file("new.txt", "outputs/new.txt")];
    fireEvent.click(folder);
    expect(await screen.findByText("new.txt")).toBeInTheDocument();
  });

  it("defers hidden refreshes, preserves scroll, and refreshes on activation", async () => {
    const sessionId = "retained-files";
    let entries = [file("old.txt", "outputs/old.txt")];
    mockedFetchDirectoryListing.mockImplementation(async (_id, path) => ({
      path: path ?? "",
      entries: path ? entries : [outputsDirectory],
    }));
    const store = () => useBuildSessionStore.getState();
    store().createSession(sessionId, {
      filesTabState: { expandedPaths: ["outputs"], scrollTop: 0 },
    });
    const { rerender } = render(<FilesTab sessionId={sessionId} />);
    const oldFile = await screen.findByText("old.txt");
    const container = oldFile.closest(".overflow-auto");
    if (!container) throw new Error("missing scroll container");
    fireEvent.scroll(container, { target: { scrollTop: 120 } });
    expect(store().sessions.get(sessionId)?.filesTabState.scrollTop).toBe(0);
    rerender(<FilesTab sessionId={sessionId} isActive={false} />);
    expect(store().sessions.get(sessionId)?.filesTabState.scrollTop).toBe(120);
    const requests = mockedFetchDirectoryListing.mock.calls.length;
    entries = [file("new.txt", "outputs/new.txt")];
    act(() => store().triggerFilesRefresh(sessionId));
    expect(mockedFetchDirectoryListing).toHaveBeenCalledTimes(requests);
    expect(screen.getByText("old.txt")).toBe(oldFile);
    rerender(<FilesTab sessionId={sessionId} />);
    expect(await screen.findByText("new.txt")).toBeInTheDocument();
    expect(container.scrollTop).toBe(120);
  });

  it("does not let a stalled folder block another folder or a remount", async () => {
    const sessionId = "stalled-folder";
    const other = { ...outputsDirectory, name: "other", path: "other" };
    const signals: AbortSignal[] = [];
    mockedFetchDirectoryListing.mockImplementation(
      async (_id, path, signal) => {
        if (!path) return { path: "", entries: [outputsDirectory, other] };
        if (path === "outputs") {
          if (signal) signals.push(signal);
          return new Promise<DirectoryListing>(() => {});
        }
        return { path, entries: [file("notes.txt", "other/notes.txt")] };
      }
    );
    useBuildSessionStore.getState().createSession(sessionId);
    const { unmount } = render(<FilesTab sessionId={sessionId} />);
    fireEvent.click(await screen.findByRole("button", { name: "outputs" }));
    await waitFor(() => expect(signals).toHaveLength(1));
    expect(screen.getByRole("button", { name: "outputs" })).toHaveAttribute(
      "aria-busy",
      "true"
    );
    expect(screen.queryByText("Loading files...")).not.toBeInTheDocument();
    expect(
      screen.queryByText("No files in this directory")
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "other" }));
    expect(await screen.findByText("notes.txt")).toBeInTheDocument();
    unmount();
    expect(signals[0]?.aborted).toBe(true);
    mockedFetchDirectoryListing.mockImplementation(async (_id, path) => ({
      path: path ?? "",
      entries:
        path === "outputs"
          ? [file("recovered.txt", "outputs/recovered.txt")]
          : path
            ? []
            : [outputsDirectory, other],
    }));
    render(<FilesTab sessionId={sessionId} />);
    expect(await screen.findByText("recovered.txt")).toBeInTheDocument();
  });

  it("aborts an in-flight request when hidden and reports a fetch failure", async () => {
    const sessionId = "cancel-folder";
    let requestSignal: AbortSignal | undefined;
    mockedFetchDirectoryListing.mockImplementation(
      async (_id, path, signal) => {
        if (!path) return { path: "", entries: [outputsDirectory] };
        requestSignal = signal;
        return new Promise<DirectoryListing>(() => {});
      }
    );
    useBuildSessionStore.getState().createSession(sessionId);
    const { rerender } = render(<FilesTab sessionId={sessionId} />);
    fireEvent.click(await screen.findByRole("button", { name: "outputs" }));
    await waitFor(() => expect(requestSignal).toBeDefined());
    rerender(<FilesTab sessionId={sessionId} isActive={false} />);
    expect(requestSignal?.aborted).toBe(true);
    mockedFetchDirectoryListing.mockRejectedValue(new Error("Unavailable"));
    rerender(<FilesTab sessionId={sessionId} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "outputs" })).toHaveAttribute(
        "title",
        "Error loading files"
      )
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("restores saved scroll after the root listing arrives", async () => {
    const sessionId = "saved-scroll";
    let finishRoot: (listing: DirectoryListing) => void = () => {};
    const root = new Promise<DirectoryListing>((resolve) => {
      finishRoot = resolve;
    });
    mockedFetchDirectoryListing.mockReturnValue(root);
    useBuildSessionStore.getState().createSession(sessionId, {
      filesTabState: { expandedPaths: [], scrollTop: 120 },
    });
    render(<FilesTab sessionId={sessionId} />);
    expect(
      screen.queryByRole("button", { name: "outputs" })
    ).not.toBeInTheDocument();
    await act(async () => {
      finishRoot({ path: "", entries: [outputsDirectory] });
    });
    const folder = await screen.findByRole("button", { name: "outputs" });
    expect(folder.closest(".overflow-auto")?.scrollTop).toBe(120);
  });

  it("restores Files scroll when returning from an inline preview", async () => {
    const sessionId = "preview-scroll";
    mockedFetchDirectoryListing.mockResolvedValue({
      path: "",
      entries: [file("notes.md", "outputs/notes.md")],
    });
    useBuildSessionStore.getState().createSession(sessionId);
    const { rerender } = render(
      <FilesTab sessionId={sessionId} isPreProvisioned />
    );
    const entry = await screen.findByRole("button", { name: /notes.md/ });
    const container = entry.closest(".overflow-auto");
    if (!container) throw new Error("Files scroll container is missing");
    fireEvent.scroll(container, { target: { scrollTop: 120 } });
    // Removing the tree can reset DOM scroll before its ref cleanup runs.
    container.scrollTop = 0;
    fireEvent.click(entry);
    expect(screen.getByTestId("inline-preview")).toBeInTheDocument();
    expect(
      useBuildSessionStore.getState().sessions.get(sessionId)?.filesTabState
        .scrollTop
    ).toBe(120);
    rerender(<FilesTab sessionId={sessionId} />);

    fireEvent.click(screen.getByRole("button"));

    expect(
      screen.getByRole("button", { name: /notes.md/ }).closest(".overflow-auto")
        ?.scrollTop
    ).toBe(120);
  });

  it("refreshes a welcome-page preview after the first message handoff", async () => {
    const sessionId = "inline-handoff";
    const path = "outputs/notes.md";
    mockedFetchDirectoryListing.mockResolvedValue({
      path: "",
      entries: [file("notes.md", path)],
    });
    const store = () => useBuildSessionStore.getState();
    store().createSession(sessionId);
    const { rerender } = render(
      <FilesTab sessionId={sessionId} isPreProvisioned />
    );
    fireEvent.click(await screen.findByRole("button", { name: /notes.md/ }));
    const preview = screen.getByTestId("inline-preview");
    expect(preview).not.toHaveAttribute("data-revision");
    rerender(<FilesTab sessionId={sessionId} />);
    act(() =>
      store().updateSessionData(sessionId, {
        outputInventory: { [path]: { path, revision: "123:100", size: 100 } },
      })
    );
    expect(screen.getByTestId("inline-preview")).toBe(preview);
    expect(preview).toHaveAttribute("data-revision", "123:100");
  });
});

it("does not show cancellation errors when directory reads restart", async () => {
  const requests: Array<{
    signal: AbortSignal;
    resolve: (listing: DirectoryListing) => void;
  }> = [];
  mockedFetchDirectoryListing.mockReset();
  mockedFetchDirectoryListing.mockImplementation(
    (_id, _path, signal) =>
      new Promise((resolve, reject) => {
        if (!signal) throw new Error("Missing request signal");
        signal.addEventListener("abort", () =>
          reject(new DOMException("Cancelled", "AbortError"))
        );
        requests.push({ signal, resolve });
      })
  );
  useBuildSessionStore.getState().createSession("strict-files");
  const { rerender } = render(<FilesTab sessionId="strict-files" />);
  await waitFor(() => expect(requests).toHaveLength(1));
  rerender(<FilesTab sessionId="strict-files" isActive={false} />);
  await act(async () => {});
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  rerender(<FilesTab sessionId="strict-files" />);
  await waitFor(() => expect(requests.length).toBeGreaterThanOrEqual(2));
  expect(requests[0]?.signal.aborted).toBe(true);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await act(async () => {
    requests
      .findLast((request) => !request.signal.aborted)
      ?.resolve({ path: "", entries: [outputsDirectory] });
  });
  expect(
    await screen.findByRole("button", { name: "outputs" })
  ).toBeInTheDocument();
  expect(screen.queryByText("Error loading files")).not.toBeInTheDocument();
});

it("keeps the folder spinner until the current request finishes after an older cancellation", async () => {
  const requests: Array<{
    signal: AbortSignal;
    resolve: (listing: DirectoryListing) => void;
  }> = [];
  mockedFetchDirectoryListing.mockReset();
  mockedFetchDirectoryListing.mockImplementation(async (_id, path, signal) => {
    if (!path) return { path: "", entries: [outputsDirectory] };
    return new Promise((resolve, reject) => {
      if (!signal) throw new Error("Missing request signal");
      signal.addEventListener("abort", () => reject(signal.reason));
      requests.push({ signal, resolve });
    });
  });
  const sessionId = "folder-spinner";
  const store = () => useBuildSessionStore.getState();
  store().createSession(sessionId);
  render(<FilesTab sessionId={sessionId} />);
  const folder = await screen.findByRole("button", { name: "outputs" });
  fireEvent.click(folder);
  await waitFor(() => expect(requests).toHaveLength(1));
  await act(async () => store().triggerFilesRefresh(sessionId));
  expect(requests).toHaveLength(2);
  expect(requests[0]?.signal.aborted).toBe(true);
  expect(folder).toHaveAttribute("aria-busy", "true");
  expect(screen.queryByText("Loading files...")).not.toBeInTheDocument();
  expect(screen.queryByText("Error loading files")).not.toBeInTheDocument();
  await act(async () => requests[1]?.resolve({ path: "outputs", entries: [] }));
  await waitFor(() => expect(folder).not.toHaveAttribute("aria-busy"));
  expect(
    screen.queryByText("No files in this directory")
  ).not.toBeInTheDocument();
});

it.each([50, 250])(
  "keeps the folder loading icon visible for at least 150ms after a %ims request",
  async (requestDuration) => {
    jest.useFakeTimers();
    const requests: Array<(listing: DirectoryListing) => void> = [];
    mockedFetchDirectoryListing.mockReset();
    mockedFetchDirectoryListing.mockImplementation(async (_id, path) => {
      if (!path) return { path: "", entries: [outputsDirectory] };
      return new Promise((resolve) => requests.push(resolve));
    });
    const sessionId = `minimum-folder-loading-${requestDuration}`;
    useBuildSessionStore.getState().createSession(sessionId);
    const view = render(<FilesTab sessionId={sessionId} />);
    try {
      await act(async () => {});
      const folder = screen.getByRole("button", { name: "outputs" });
      fireEvent.click(folder);
      expect(folder).toHaveAttribute("aria-busy", "true");
      await act(async () => jest.advanceTimersByTimeAsync(requestDuration));
      await act(async () =>
        requests[0]?.({
          path: "outputs",
          entries: [file("ready.txt", "outputs/ready.txt")],
        })
      );
      // Content is usable immediately, even while the icon finishes displaying.
      expect(screen.getByText("ready.txt")).toBeInTheDocument();
      if (requestDuration < 150) {
        expect(folder).toHaveAttribute("aria-busy", "true");
        await act(async () =>
          jest.advanceTimersByTimeAsync(149 - requestDuration)
        );
        expect(folder).toHaveAttribute("aria-busy", "true");
        await act(async () => jest.advanceTimersByTimeAsync(1));
      }
      expect(folder).not.toHaveAttribute("aria-busy");
    } finally {
      view.unmount();
      jest.useRealTimers();
    }
  }
);
