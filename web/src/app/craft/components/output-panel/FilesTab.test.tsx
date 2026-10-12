import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import { FetchError } from "@/lib/fetcher";
import { readWorkspaceDirectorySnapshot } from "@/app/craft/services/workspaceDirectorySnapshots";
import { DirectoryTree } from "@/app/craft/components/output-panel/DirectoryTree";
import FilesTab from "@/app/craft/components/output-panel/FilesTab";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchDirectoryListing,
  downloadArtifactFile,
  downloadDirectory,
} from "@/app/craft/services/apiServices";
import type {
  DirectoryListing,
  FileSystemEntry,
} from "@/app/craft/types/streamingTypes";

let mockUserId = "test-user";
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: mockUserId } }),
}));

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchDirectoryListing: jest.fn(),
  downloadArtifactFile: jest.fn(),
  downloadDirectory: jest.fn(),
}));
const listing = jest.mocked(fetchDirectoryListing);
function file(name: string, path: string): FileSystemEntry {
  return { name, path, is_directory: false, size: 10, mime_type: "text/plain" };
}
const outputs: FileSystemEntry = {
  name: "outputs",
  path: "outputs",
  is_directory: true,
  size: null,
  mime_type: null,
};

beforeEach(() => {
  mockUserId = "test-user";
  jest.clearAllMocks();
  window.sessionStorage.clear();
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    preProvisioning: { status: "idle" },
    sessionHistory: [],
  });
  useBuildSessionStore.getState().createSession("session");
});

it("opens outputs initially and opens a resource without replacing the tree", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("notes.md", "outputs/notes.md")] : [outputs],
  }));
  const onFileClick = jest.fn();
  render(<FilesTab sessionId="session" onFileClick={onFileClick} />);
  fireEvent.click(await screen.findByRole("button", { name: "notes.md" }));
  expect(onFileClick).toHaveBeenCalledWith("outputs/notes.md", "notes.md");
  expect(screen.getByRole("button", { name: "outputs" })).toHaveAttribute(
    "aria-expanded",
    "true"
  );
});

it("keeps useful files during reload and rejects a superseded listing", async () => {
  const first = deferred<DirectoryListing>();
  const second = deferred<DirectoryListing>();
  let children = 0;
  listing.mockImplementation(async (_session, path) => {
    if (!path) return { path: "", entries: [outputs] };
    children++;
    if (children === 1)
      return { path, entries: [file("old.txt", "outputs/old.txt")] };
    return children === 2 ? first.promise : second.promise;
  });
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "old.txt" });
  rerender(<FilesTab sessionId="session" refreshKey={1} />);
  await waitFor(() => expect(children).toBe(2));
  expect(screen.getByRole("button", { name: "old.txt" })).toBeInTheDocument();
  rerender(<FilesTab sessionId="session" refreshKey={2} />);
  await waitFor(() => expect(children).toBe(3));
  await act(async () =>
    second.resolve({
      path: "outputs",
      entries: [file("new.txt", "outputs/new.txt")],
    })
  );
  await screen.findByRole("button", { name: "new.txt" });
  await act(async () =>
    first.resolve({
      path: "outputs",
      entries: [file("stale.txt", "outputs/stale.txt")],
    })
  );
  expect(screen.queryByText("stale.txt")).not.toBeInTheDocument();
});

it("retains old files when refresh fails", async () => {
  listing.mockResolvedValue({
    path: "",
    entries: [file("notes.txt", "notes.txt")],
  });
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "notes.txt" });
  listing.mockRejectedValue(new Error("offline"));
  rerender(<FilesTab sessionId="session" refreshKey={1} />);
  await screen.findByText("Error loading files");
  expect(screen.getByRole("button", { name: "notes.txt" })).toBeInTheDocument();
});

it("searches collapsed directories and returns to the same tree", async () => {
  const nested = { ...outputs, name: "scripts", path: "scripts" };
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("report.txt", "scripts/report.txt")] : [nested],
  }));
  const { rerender } = render(<FilesTab sessionId="session" />);
  const tree = await screen.findByRole("button", { name: "scripts" });
  expect(tree).toHaveAttribute("aria-expanded", "false");
  const container = tree.closest(".overflow-auto");
  if (!container) throw new Error("No scroll container");
  fireEvent.scroll(container, { target: { scrollTop: 120 } });
  rerender(<FilesTab sessionId="session" searchQuery="REPORT" />);
  await screen.findByRole("button", { name: "scripts/report.txt" });
  rerender(<FilesTab sessionId="session" searchQuery="" />);
  expect(screen.getByRole("button", { name: "scripts" })).toBe(tree);
  expect(container.scrollTop).toBe(120);
  expect(tree).toHaveAttribute("aria-expanded", "false");
});

it.each([
  { name: "notes.txt", mimeType: "text/plain" },
  { name: "photo.png", mimeType: "image/png" },
])("downloads $name without an attach action", async ({ name, mimeType }) => {
  listing.mockResolvedValue({
    path: "",
    entries: [{ ...file(name, name), mime_type: mimeType }],
  });
  render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name });
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(downloadArtifactFile).toHaveBeenCalledWith("session", name);
  expect(
    screen.queryByRole("button", { name: "Attach to chat" })
  ).not.toBeInTheDocument();
});

it.each([401, 403, 404])(
  "removes retained directory rows after access loss (%s)",
  async (status) => {
    listing.mockResolvedValue({
      path: "",
      entries: [file("private.txt", "private.txt")],
    });
    const { rerender } = render(<FilesTab sessionId="session" />);
    await screen.findByRole("button", { name: "private.txt" });
    listing.mockRejectedValue(new FetchError("Unavailable", status, null));
    rerender(<FilesTab sessionId="session" refreshKey={1} />);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "private.txt" })
      ).not.toBeInTheDocument()
    );
    await waitFor(() =>
      expect(
        readWorkspaceDirectorySnapshot("test-user", "session", "")
      ).toBeUndefined()
    );
  }
);

it("keeps prior search hits when a folder refresh is incomplete", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("report.txt", "outputs/report.txt")] : [outputs],
  }));
  const { rerender } = render(
    <FilesTab sessionId="session" searchQuery="report" />
  );
  await screen.findByRole("button", { name: "outputs/report.txt" });
  listing.mockImplementation(async (_session, path) => {
    if (path) throw new Error("Temporary folder failure");
    return { path: "", entries: [outputs] };
  });
  rerender(
    <FilesTab sessionId="session" searchQuery="report" refreshKey={1} />
  );
  await screen.findByText(
    "Some folders could not be loaded. Refresh to try again."
  );
  expect(
    screen.getByRole("button", { name: "outputs/report.txt" })
  ).toBeInTheDocument();
});

it("reuses fresh directory listings across panel and folder reopen", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("notes.txt", "outputs/notes.txt")] : [outputs],
  }));
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "notes.txt" });
  expect(listing).toHaveBeenCalledTimes(2);
  rerender(<FilesTab sessionId="session" isActive={false} />);
  rerender(<FilesTab sessionId="session" isActive />);
  fireEvent.click(screen.getByRole("button", { name: "outputs" }));
  fireEvent.click(screen.getByRole("button", { name: "outputs" }));
  await screen.findByRole("button", { name: "notes.txt" });
  expect(listing).toHaveBeenCalledTimes(2);
});

it("refreshes stale listings in the background while keeping their rows", async () => {
  let now = Date.now();
  const clock = jest.spyOn(Date, "now").mockImplementation(() => now);
  const refresh = deferred<DirectoryListing>();
  listing
    .mockResolvedValueOnce({
      path: "",
      entries: [file("old.txt", "old.txt")],
    })
    .mockReturnValueOnce(refresh.promise);
  try {
    const { rerender } = render(<FilesTab sessionId="session" canLoad />);
    await screen.findByRole("button", { name: "old.txt" });
    rerender(<FilesTab sessionId="session" canLoad isActive={false} />);
    now += 30_001;
    rerender(<FilesTab sessionId="session" canLoad isActive />);
    await waitFor(() => expect(listing).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "old.txt" })).toBeInTheDocument();
    await act(async () =>
      refresh.resolve({
        path: "",
        entries: [file("new.txt", "new.txt")],
      })
    );
    await screen.findByRole("button", { name: "new.txt" });
  } finally {
    clock.mockRestore();
  }
});

it("bypasses freshness for explicit reload and hidden file changes", async () => {
  listing.mockResolvedValue({
    path: "",
    entries: [file("notes.txt", "notes.txt")],
  });
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "notes.txt" });
  rerender(<FilesTab sessionId="session" refreshKey={1} />);
  await waitFor(() => expect(listing).toHaveBeenCalledTimes(2));
  await act(async () => {});
  rerender(<FilesTab sessionId="session" refreshKey={1} isActive={false} />);
  act(() => useBuildSessionStore.getState().triggerFilesRefresh("session"));
  expect(listing).toHaveBeenCalledTimes(2);
  rerender(<FilesTab sessionId="session" refreshKey={1} isActive />);
  await waitFor(() => expect(listing).toHaveBeenCalledTimes(3));
});

it("retries a failed listing on immediate reopen", async () => {
  listing.mockRejectedValueOnce(new Error("offline"));
  const { rerender } = render(<FilesTab sessionId="session" canLoad />);
  await screen.findByText("Error loading files");
  listing.mockResolvedValue({
    path: "",
    entries: [file("recovered.txt", "recovered.txt")],
  });
  rerender(<FilesTab sessionId="session" canLoad isActive={false} />);
  rerender(<FilesTab sessionId="session" canLoad isActive />);
  await screen.findByRole("button", { name: "recovered.txt" });
  expect(listing).toHaveBeenCalledTimes(2);
});

it("reuses recursive search inventory across quick panel and search reopen", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("report.txt", "outputs/report.txt")] : [outputs],
  }));
  const { rerender } = render(
    <FilesTab sessionId="session" searchQuery="report" />
  );
  await screen.findByRole("button", { name: "outputs/report.txt" });
  expect(listing).toHaveBeenCalledTimes(2);
  rerender(
    <FilesTab sessionId="session" searchQuery="report" isActive={false} />
  );
  rerender(<FilesTab sessionId="session" searchQuery="report" isActive />);
  expect(listing).toHaveBeenCalledTimes(2);
  rerender(<FilesTab sessionId="session" searchQuery="" />);
  await screen.findByRole("button", { name: "report.txt" });
  const count = listing.mock.calls.length;
  rerender(<FilesTab sessionId="session" searchQuery="report" />);
  await screen.findByRole("button", { name: "outputs/report.txt" });
  expect(listing).toHaveBeenCalledTimes(count);
});

it("retains search hits only under failed folders during a partial refresh", async () => {
  const reports = { ...outputs, name: "reports", path: "reports" };
  const archive = { ...outputs, name: "archive", path: "archive" };
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: !path
      ? [reports, archive]
      : [file("report.txt", `${path}/report.txt`)],
  }));
  const { rerender } = render(
    <FilesTab sessionId="session" searchQuery="report" />
  );
  await screen.findByRole("button", { name: "reports/report.txt" });
  await screen.findByRole("button", { name: "archive/report.txt" });
  listing.mockImplementation(async (_session, path) => {
    if (path === "archive") throw new Error("Unavailable archive");
    return { path: path ?? "", entries: path ? [] : [reports, archive] };
  });
  rerender(
    <FilesTab sessionId="session" searchQuery="report" refreshKey={1} />
  );
  await screen.findByText(
    "Some folders could not be loaded. Refresh to try again."
  );
  expect(
    screen.queryByRole("button", { name: "reports/report.txt" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "archive/report.txt" })
  ).toBeInTheDocument();
});

it("spins in the folder icon slot while its directory loads", async () => {
  const pending = deferred<DirectoryListing>();
  listing.mockImplementation((_session, path) =>
    path ? pending.promise : Promise.resolve({ path: "", entries: [outputs] })
  );
  render(<FilesTab sessionId="session" />);
  const folder = await screen.findByRole("button", { name: "outputs" });
  await waitFor(() => expect(folder).toHaveAttribute("aria-busy", "true"));
  const spinner = folder.querySelector(".motion-safe\\:animate-spin");
  expect(spinner).not.toBeNull();
  const iconSlot = spinner?.parentElement;
  await act(async () => pending.resolve({ path: "outputs", entries: [] }));
  await waitFor(() => expect(folder).not.toHaveAttribute("aria-busy"));
  await waitFor(() =>
    expect(folder.querySelector(".motion-safe\\:animate-spin")).toBeNull()
  );
  const folderIcon = folder.querySelector("svg");
  expect(folderIcon?.parentElement).toBe(iconSlot);
});

it("keeps each session's fresh directory cache across session switches", async () => {
  useBuildSessionStore.getState().createSession("other");
  listing.mockImplementation(async (id, path) => ({
    path: path ?? "",
    entries: path ? [file(`${id}.txt`, `outputs/${id}.txt`)] : [outputs],
  }));
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "session.txt" });
  act(() => useBuildSessionStore.getState().triggerFilesRefresh("session"));
  await waitFor(() => expect(listing).toHaveBeenCalledTimes(4));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "outputs" })).not.toHaveAttribute(
      "aria-busy"
    )
  );
  rerender(<FilesTab sessionId="other" />);
  await screen.findByRole("button", { name: "other.txt" });
  expect(
    screen.queryByRole("button", { name: "session.txt" })
  ).not.toBeInTheDocument();
  expect(listing).toHaveBeenCalledTimes(6);
  rerender(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "session.txt" });
  expect(
    screen.queryByRole("button", { name: "other.txt" })
  ).not.toBeInTheDocument();
  expect(listing).toHaveBeenCalledTimes(6);
});

it("keeps restored expansion until the current active listing confirms a folder is gone", async () => {
  const refresh = deferred<DirectoryListing>();
  listing
    .mockResolvedValueOnce({ path: "", entries: [] })
    .mockReturnValueOnce(refresh.promise);
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByText("No files yet");
  rerender(<FilesTab sessionId="session" isActive={false} refreshKey={1} />);
  act(() =>
    useBuildSessionStore.getState().updateFilesTabState("session", {
      expandedPaths: ["outputs", "outputs/nested"],
    })
  );
  const expansion = () =>
    useBuildSessionStore.getState().sessions.get("session")?.filesTabState
      .expandedPaths;
  expect(expansion()).toEqual(["outputs", "outputs/nested"]);
  rerender(<FilesTab sessionId="session" isActive refreshKey={1} />);
  await waitFor(() => expect(listing).toHaveBeenCalledTimes(2));
  expect(expansion()).toEqual(["outputs", "outputs/nested"]);
  await act(async () => refresh.resolve({ path: "", entries: [] }));
  await waitFor(() => expect(expansion()).toEqual([]));
});

it("shows a failed refresh instead of a cached empty directory message", async () => {
  listing.mockResolvedValueOnce({ path: "", entries: [] });
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByText("No files yet");
  listing.mockRejectedValueOnce(new Error("offline"));
  rerender(<FilesTab sessionId="session" refreshKey={1} />);
  await screen.findByRole("alert");
  expect(screen.getByText("Error loading files")).toBeInTheDocument();
  expect(screen.queryByText("No files yet")).not.toBeInTheDocument();
});

it("keeps reconciled expansion state when a missing outputs folder returns", async () => {
  useBuildSessionStore.getState().createSession("other");
  listing.mockResolvedValue({ path: "", entries: [] });
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByText("No files yet");
  rerender(<FilesTab sessionId="other" />);
  await screen.findByText("No files yet");
  rerender(<FilesTab sessionId="session" isActive={false} refreshKey={1} />);
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("restored.txt", "outputs/restored.txt")] : [outputs],
  }));
  rerender(<FilesTab sessionId="session" isActive refreshKey={1} />);
  expect(
    await screen.findByRole("button", { name: "outputs" })
  ).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(screen.getByRole("button", { name: "outputs" }));
  await screen.findByRole("button", { name: "restored.txt" });
});

it("reports a newly opened folder as loading before the fetch effect starts", async () => {
  const pending = deferred<DirectoryListing>();
  listing.mockReturnValue(pending.promise);
  const onStatusChange = jest.fn();
  render(
    <DirectoryTree
      sessionId="session"
      path="outputs"
      depth={1}
      isActive
      refreshGeneration={0}
      onStatusChange={onStatusChange}
      expandedPaths={new Set(["outputs"])}
      onToggleFolder={jest.fn()}
      onFileClick={jest.fn()}
    />
  );
  expect(onStatusChange).toHaveBeenNthCalledWith(1, "outputs", "loading");
  await act(async () => pending.resolve({ path: "outputs", entries: [] }));
  await waitFor(() =>
    expect(onStatusChange).toHaveBeenLastCalledWith("outputs", undefined)
  );
});

it("shows persisted directory rows immediately after a new SWR provider mounts and reconciles in the background", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("cached.txt", "outputs/cached.txt")] : [outputs],
  }));
  const first = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "cached.txt" });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "outputs" })).not.toHaveAttribute(
      "aria-busy"
    )
  );
  first.unmount();
  const root = deferred<DirectoryListing>();
  const child = deferred<DirectoryListing>();
  listing.mockImplementation((_session, path) =>
    path ? child.promise : root.promise
  );
  render(<FilesTab sessionId="session" />);
  expect(
    screen.getByRole("button", { name: "cached.txt" })
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "outputs" })).toHaveAttribute(
    "aria-busy",
    "true"
  );
  await waitFor(() => expect(listing).toHaveBeenCalledTimes(4));
  await act(async () => {
    root.resolve({ path: "", entries: [outputs] });
    child.resolve({
      path: "outputs",
      entries: [file("fresh.txt", "outputs/fresh.txt")],
    });
  });
  await screen.findByRole("button", { name: "fresh.txt" });
  expect(
    screen.queryByRole("button", { name: "cached.txt" })
  ).not.toBeInTheDocument();
});

it("reuses fresh directory rows after Files closes and truly unmounts", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("cached.txt", "outputs/cached.txt")] : [outputs],
  }));
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "cached.txt" });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "outputs" })).not.toHaveAttribute(
      "aria-busy"
    )
  );
  expect(listing).toHaveBeenCalledTimes(2);
  rerender(<></>);
  expect(
    screen.queryByRole("button", { name: "cached.txt" })
  ).not.toBeInTheDocument();
  rerender(<FilesTab sessionId="session" />);
  expect(
    screen.getByRole("button", { name: "cached.txt" })
  ).toBeInTheDocument();
  await act(async () => {});
  expect(listing).toHaveBeenCalledTimes(2);
});

it("downloads a folder without toggling its expansion", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [] : [outputs],
  }));
  render(<FilesTab sessionId="session" />);
  const folder = await screen.findByRole("button", { name: "outputs" });
  await waitFor(() => expect(folder).toHaveAttribute("aria-expanded", "true"));
  fireEvent.click(folder);
  expect(folder).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  expect(downloadDirectory).toHaveBeenCalledWith("session", "outputs");
  expect(folder).toHaveAttribute("aria-expanded", "false");
});

// Loading has one owner per directory, with a primitive aggregate for the toolbar.
it("keeps the toolbar busy until every expanded directory has settled", async () => {
  const first = deferred<DirectoryListing>();
  const second = deferred<DirectoryListing>();
  const nested = { ...outputs, name: "other", path: "other" };
  useBuildSessionStore
    .getState()
    .updateFilesTabState("session", { expandedPaths: ["outputs", "other"] });
  listing.mockImplementation((_session, path) =>
    path === "outputs"
      ? first.promise
      : path === "other"
        ? second.promise
        : Promise.resolve({ path: "", entries: [outputs, nested] })
  );
  const onRefreshingChange = jest.fn();
  render(
    <FilesTab sessionId="session" onRefreshingChange={onRefreshingChange} />
  );
  await waitFor(() => expect(listing).toHaveBeenCalledTimes(3));
  expect(onRefreshingChange).toHaveBeenLastCalledWith(true);
  await act(async () => first.resolve({ path: "outputs", entries: [] }));
  expect(onRefreshingChange).toHaveBeenLastCalledWith(true);
  await act(async () => second.resolve({ path: "other", entries: [] }));
  await waitFor(() =>
    expect(onRefreshingChange).toHaveBeenLastCalledWith(false)
  );
});

it("releases a collapsed directory's loading state and ignores its late response", async () => {
  const pending = deferred<DirectoryListing>();
  listing.mockImplementation((_session, path) =>
    path ? pending.promise : Promise.resolve({ path: "", entries: [outputs] })
  );
  const onRefreshingChange = jest.fn();
  render(
    <FilesTab sessionId="session" onRefreshingChange={onRefreshingChange} />
  );
  const folder = await screen.findByRole("button", { name: "outputs" });
  await waitFor(() => expect(folder).toHaveAttribute("aria-busy", "true"));
  fireEvent.click(folder);
  await waitFor(() =>
    expect(onRefreshingChange).toHaveBeenLastCalledWith(false)
  );
  const reported = onRefreshingChange.mock.calls.length;
  await act(async () =>
    pending.resolve({
      path: "outputs",
      entries: [file("late.txt", "outputs/late.txt")],
    })
  );
  expect(onRefreshingChange).toHaveBeenCalledTimes(reported);
  expect(
    screen.queryByRole("button", { name: "late.txt" })
  ).not.toBeInTheDocument();
});

it("does not reuse another user's directory rows at the same session URL", async () => {
  listing.mockImplementation(async () => ({
    path: "",
    entries: [file(`${mockUserId}.txt`, `${mockUserId}.txt`)],
  }));
  const { rerender } = render(<FilesTab sessionId="session" />);
  await screen.findByRole("button", { name: "test-user.txt" });
  mockUserId = "new-user";
  rerender(<FilesTab sessionId="session" />);
  expect(
    screen.queryByRole("button", { name: "test-user.txt" })
  ).not.toBeInTheDocument();
  await screen.findByRole("button", { name: "new-user.txt" });
  expect(listing).toHaveBeenCalledTimes(2);
});

it("retains failed-folder search hits after the search component was remounted", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [file("report.txt", "outputs/report.txt")] : [outputs],
  }));
  const { rerender } = render(
    <FilesTab sessionId="session" searchQuery="report" />
  );
  await screen.findByRole("button", { name: "outputs/report.txt" });
  rerender(<FilesTab sessionId="session" searchQuery="" />);
  await screen.findByRole("button", { name: "report.txt" });
  listing.mockImplementation(async (_session, path) => {
    if (path) throw new Error("temporary");
    return { path: "", entries: [outputs] };
  });
  rerender(
    <FilesTab sessionId="session" searchQuery="report" refreshKey={1} />
  );
  await screen.findByText(
    "Some folders could not be loaded. Refresh to try again."
  );
  expect(
    screen.getByRole("button", { name: "outputs/report.txt" })
  ).toBeInTheDocument();
});

// Directory loading indicators.
it.each([50, 250])(
  "keeps a folder loading icon steady without delaying rows after a %ims request",
  async (requestDuration) => {
    jest.useFakeTimers();
    const pending = deferred<DirectoryListing>();
    listing.mockImplementation(async (_session, path) =>
      path ? pending.promise : { path: "", entries: [outputs] }
    );
    const onRefreshingChange = jest.fn();
    const view = render(
      <FilesTab sessionId="session" onRefreshingChange={onRefreshingChange} />
    );
    try {
      await act(async () => {});
      const folder = screen.getByRole("button", { name: "outputs" });
      expect(folder).toHaveAttribute("aria-busy", "true");
      await act(async () => jest.advanceTimersByTimeAsync(requestDuration));
      await act(async () =>
        pending.resolve({
          path: "outputs",
          entries: [file("ready.txt", "outputs/ready.txt")],
        })
      );
      expect(screen.getByText("ready.txt")).toBeInTheDocument();
      expect(onRefreshingChange).toHaveBeenLastCalledWith(false);
      expect(folder).not.toHaveAttribute("aria-busy");
      if (requestDuration < 150) {
        expect(
          folder.querySelector(".motion-safe\\:animate-spin")
        ).not.toBeNull();
        await act(async () =>
          jest.advanceTimersByTimeAsync(149 - requestDuration)
        );
        expect(
          folder.querySelector(".motion-safe\\:animate-spin")
        ).not.toBeNull();
        await act(async () => jest.advanceTimersByTimeAsync(1));
      }
      expect(folder.querySelector(".motion-safe\\:animate-spin")).toBeNull();
    } finally {
      view.unmount();
      jest.useRealTimers();
    }
  }
);

it("keeps the current folder request busy when an older request is canceled", async () => {
  const requests: Array<{
    signal: AbortSignal;
    resolve: (listing: DirectoryListing) => void;
  }> = [];
  listing.mockImplementation(async (_session, path, signal) => {
    if (!path) return { path: "", entries: [outputs] };
    return new Promise((resolve, reject) => {
      if (!signal) throw new Error("Missing signal");
      signal.addEventListener("abort", () => reject(signal.reason));
      requests.push({ signal, resolve });
    });
  });
  const onRefreshingChange = jest.fn();
  const { rerender } = render(
    <FilesTab sessionId="session" onRefreshingChange={onRefreshingChange} />
  );
  await waitFor(() => expect(requests).toHaveLength(1));
  rerender(
    <FilesTab
      sessionId="session"
      refreshKey={1}
      onRefreshingChange={onRefreshingChange}
    />
  );
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0]?.signal.aborted).toBe(true);
  expect(screen.getByRole("button", { name: "outputs" })).toHaveAttribute(
    "aria-busy",
    "true"
  );
  expect(onRefreshingChange).toHaveBeenLastCalledWith(true);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  await act(async () => requests[1]?.resolve({ path: "outputs", entries: [] }));
  await waitFor(() =>
    expect(onRefreshingChange).toHaveBeenLastCalledWith(false)
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "outputs" })).not.toHaveAttribute(
      "aria-busy"
    )
  );
});

it("preserves an explicitly collapsed tree when the Files browser remounts", async () => {
  listing.mockImplementation(async (_session, path) => ({
    path: path ?? "",
    entries: path ? [] : [outputs],
  }));
  const view = render(<FilesTab sessionId="session" onFileClick={jest.fn()} />);
  const folder = await screen.findByRole("button", { name: "outputs" });
  expect(folder).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(folder);
  view.unmount();
  render(<FilesTab sessionId="session" onFileClick={jest.fn()} />);
  expect(
    await screen.findByRole("button", { name: "outputs" })
  ).toHaveAttribute("aria-expanded", "false");
});
