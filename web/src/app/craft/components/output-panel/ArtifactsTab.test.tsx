import {
  act,
  fireEvent,
  render,
  screen,
  within,
} from "@tests/setup/test-utils";
import ArtifactsTab from "@/app/craft/components/output-panel/ArtifactsTab";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  downloadArtifactFile,
  downloadDirectory,
  fetchDirectoryListing,
  fetchOutputInventory,
} from "@/app/craft/services/apiServices";
import type { OutputFile } from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices", () => ({
  fetchOutputInventory: jest.fn(),
  fetchDirectoryListing: jest.fn(),
  downloadArtifactFile: jest.fn(),
  downloadDirectory: jest.fn(),
}));

const sessionId = "artifact-folders";
const store = () => useBuildSessionStore.getState();
function file(path: string, revision = "1"): OutputFile {
  return { path, revision, size: 100 };
}
async function refresh(files: OutputFile[], complete = true) {
  jest.mocked(fetchOutputInventory).mockResolvedValue({ files, complete });
  await act(async () =>
    store().refreshOutputInventory(sessionId, { silent: true })
  );
}

beforeEach(() => {
  jest.resetAllMocks();
  useBuildSessionStore.setState({
    currentSessionId: sessionId,
    sessions: new Map(),
  });
  store().createSession(sessionId);
  jest
    .mocked(fetchOutputInventory)
    .mockResolvedValue({ files: [], complete: true });
});

it("shows known files without probing directories and preserves nested expansion on changes", async () => {
  await refresh([
    file("outputs/report.pdf"),
    file("outputs/reports/nested/old.md"),
  ]);
  render(<ArtifactsTab sessionId={sessionId} artifacts={[]} />);
  await screen.findByRole("button", { name: "Open report.pdf" });
  const reports = screen.getByRole("button", { name: "Toggle reports" });
  fireEvent.click(reports);
  const nested = screen.getByRole("button", { name: "Toggle nested" });
  fireEvent.click(nested);
  expect(
    screen.getByRole("button", { name: "Open old.md" })
  ).toBeInTheDocument();
  const scroll = reports.closest(".overflow-auto");
  if (!scroll) throw new Error("Missing scroll container");
  scroll.scrollTop = 120;

  await refresh([
    file("outputs/report.pdf"),
    file("outputs/reports/nested/new.md"),
  ]);
  expect(
    screen.getByRole("button", { name: "Open new.md" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Open old.md" })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Toggle nested" })).toBe(nested);
  expect(screen.getByRole("button", { name: "Toggle reports" })).toBe(reports);
  expect(scroll.scrollTop).toBe(120);
  expect(fetchDirectoryListing).not.toHaveBeenCalled();
});

it("retains files through incomplete scans and removes empty folders after a complete scan", async () => {
  await refresh([file("outputs/reports/old.pdf")]);
  render(<ArtifactsTab sessionId={sessionId} artifacts={[]} />);
  await screen.findByRole("button", { name: "Toggle reports" });
  await refresh([file("outputs/new.pdf")], false);
  expect(
    screen.getByRole("button", { name: "Toggle reports" })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Open new.pdf" })
  ).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Some outputs could not be listed"
  );
  await refresh([file("outputs/new.pdf")]);
  expect(
    screen.queryByRole("button", { name: "Toggle reports" })
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it("distinguishes loading and failure from a complete empty inventory", async () => {
  let rejectRequest: ((error: Error) => void) | undefined;
  jest.mocked(fetchOutputInventory).mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectRequest = reject;
      })
  );
  const warn = jest.spyOn(console, "warn").mockImplementation(() => {});
  render(<ArtifactsTab sessionId={sessionId} artifacts={[]} />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading outputs");
  await act(async () => rejectRequest?.(new Error("offline")));
  expect(screen.getByRole("status")).toHaveTextContent(
    "Could not refresh outputs"
  );
  await refresh([]);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.getByText("No artifacts yet")).toBeInTheDocument();
  warn.mockRestore();
});

it("opens files and downloads files or inferred folders through existing routes", async () => {
  await refresh([file("outputs/reports/report.pdf")]);
  render(<ArtifactsTab sessionId={sessionId} artifacts={[]} />);
  const folder = await screen.findByRole("button", { name: "Toggle reports" });
  fireEvent.click(within(folder).getByRole("button", { name: "Download" }));
  expect(downloadDirectory).toHaveBeenCalledWith(sessionId, "outputs/reports");
  fireEvent.click(folder);
  const row = screen.getByRole("button", { name: "Open report.pdf" });
  fireEvent.click(within(row).getByRole("button", { name: "Download" }));
  expect(downloadArtifactFile).toHaveBeenCalledWith(
    sessionId,
    "outputs/reports/report.pdf"
  );
  fireEvent.click(row);
  expect(store().sessions.get(sessionId)?.activePanelTabId).toBe(
    "file:outputs/reports/report.pdf"
  );
});

it("reconciles on activation without absorbing a live task's new output silently", async () => {
  await refresh([]);
  store().updateSessionData(sessionId, {
    status: "running",
    activeTurnId: "turn",
  });
  const { rerender } = render(
    <ArtifactsTab sessionId={sessionId} artifacts={[]} isActive={false} />
  );
  jest
    .mocked(fetchOutputInventory)
    .mockResolvedValue({ files: [file("outputs/new.pdf")], complete: true });
  rerender(<ArtifactsTab sessionId={sessionId} artifacts={[]} />);
  await screen.findByRole("button", { name: "Open new.pdf" });
  expect(store().sessions.get(sessionId)?.activePanelTabId).toBe(
    "file:outputs/new.pdf"
  );
});
