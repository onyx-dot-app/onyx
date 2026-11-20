import { act, render, screen, waitFor, within } from "@tests/setup/test-utils";
import { fileResponse } from "@tests/setup/fileResponse";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import {
  PublishedFilePreview,
  PublishedFilesGrid,
} from "@/sections/chat/PublishedFileViews";
import { fetchChatFile } from "@/lib/chat/svc";

jest.mock("@/lib/chat/svc", () => ({
  ...jest.requireActual("@/lib/chat/svc"),
  fetchChatFile: jest.fn(),
}));

const HTML = "<h1>Quarterly report</h1>";

afterEach(() => {
  jest.restoreAllMocks();
});

// Every observed tile is in view
function observeAllInView() {
  jest.spyOn(global, "IntersectionObserver").mockImplementation(
    (callback) =>
      ({
        observe: (target: Element) =>
          callback(
            [
              {
                isIntersecting: true,
                target,
              } as unknown as IntersectionObserverEntry,
            ],
            {} as IntersectionObserver
          ),
        unobserve: () => undefined,
        disconnect: () => undefined,
        takeRecords: () => [],
      }) as unknown as IntersectionObserver
  );
}

function file(
  fileId: string,
  name: string,
  title: string | null
): PublishedFile {
  return {
    file_id: fileId,
    name,
    title,
    path: `/home/onyx/${name}`,
    display_path: name,
    size: 2048,
    mime_type: "text/html",
    artifact_id: `artifact-${fileId}`,
    version: 1,
    thumbnail_file_id: null,
  };
}

test("the Files list shows a tile for each file, with its title, else its name", () => {
  const onOpen = jest.fn();
  const files = [
    file("file-2", "report.html", "Q3 report"),
    file("file-3", "chart.png", null),
    { ...file("file-4", "notes.md", null), display_path: "drafts/notes.md" },
    { ...file("file-5", "notes.md", null), display_path: "final/notes.md" },
  ];
  render(
    <PublishedFilesGrid
      files={files}
      unseenFileIds={[]}
      emptyLabel="No files"
      onOpen={onOpen}
    />
  );

  const tiles = screen.getAllByRole("button", { name: /^Open / });
  expect(tiles.map((tile) => tile.textContent)).toEqual([
    "Q3 report",
    "chart.png",
    "drafts/notes.md",
    "final/notes.md",
  ]);
  // Names show in their own direction
  expect(within(tiles[0]!).getByText("Q3 report")).toHaveAttribute(
    "dir",
    "auto"
  );
  // An image shows a lazy thumbnail, and its icon when the image fails.
  const thumbnail = document.querySelector("img");
  expect(thumbnail).toHaveAttribute("src", "/api/chat/file/file-3");
  expect(thumbnail).toHaveAttribute("loading", "lazy");
  act(() => {
    thumbnail?.dispatchEvent(new Event("error"));
  });
  expect(document.querySelector("img")).toBeNull();

  act(() => {
    screen.getByRole("button", { name: "Open Q3 report" }).click();
  });
  expect(onOpen).toHaveBeenCalledWith(files[0]);
});

test("a new version of a file updates its tile in place", () => {
  const first = file("file-2", "report.html", "Q3 report");
  const view = render(
    <PublishedFilesGrid
      files={[first]}
      emptyLabel="No files"
      unseenFileIds={[]}
      onOpen={jest.fn()}
    />
  );
  const tile = screen.getByRole("button", { name: "Open Q3 report" });

  view.rerender(
    <PublishedFilesGrid
      files={[
        { ...first, file_id: "file-2-v2", title: "Q4 report", version: 2 },
      ]}
      emptyLabel="No files"
      unseenFileIds={[]}
      onOpen={jest.fn()}
    />
  );
  expect(screen.getByRole("button", { name: "Open Q4 report" })).toBe(tile);
});

test("a file's preview shows HTML as source, without a download of its own", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(fileResponse(HTML, "text/html", "report.html"));
  const view = render(
    <PublishedFilePreview file={file("file-2", "report.html", "Q3 report")} />
  );

  const preview = screen.getByRole("region", { name: "Preview of Q3 report" });
  // HTML shows as source, never as a rendered page.
  await waitFor(() => expect(preview).toHaveTextContent(HTML));
  expect(view.container.querySelector("iframe")).toBeNull();
  expect(fetchChatFile).toHaveBeenCalledWith(
    "file-2",
    false,
    expect.any(AbortSignal)
  );
  // The panel's URL bar has the download
  expect(within(preview).queryByRole("link", { name: "Download" })).toBeNull();
});

test("a text tile shows the start of its file once it nears the view", async () => {
  observeAllInView();
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(
      fileResponse("# Plan\n\nShip the panel.", "text/markdown", "notes.md")
    );
  const notes = { ...file("file-6", "notes.md", null), mime_type: "" };
  const big = {
    ...file("file-7", "big.md", null),
    mime_type: "",
    size: 300 * 1024,
  };
  render(
    <PublishedFilesGrid
      files={[notes, big]}
      unseenFileIds={[]}
      emptyLabel="No files"
      onOpen={jest.fn()}
    />
  );

  const tile = screen.getByRole("button", { name: "Open notes.md" });
  await waitFor(() => expect(tile).toHaveTextContent("Ship the panel."));
  expect(tile.querySelector("h1")).toHaveTextContent("Plan");
  // A file past the text limit keeps its icon, and loads nothing
  expect(fetchChatFile).toHaveBeenCalledTimes(1);
  expect(fetchChatFile).toHaveBeenCalledWith("file-6", false, undefined);
});

test("a text tile reads its file through the preview's bounded loader", async () => {
  observeAllInView();
  // The server reports a body over the loader's text limit. A raw read of
  // the whole response would show its text.
  const response = fileResponse("# Hidden", "text/markdown", "huge.md");
  response.headers.set("Content-Length", String(6 * 1024 * 1024));
  response.text = async () => "# Hidden";
  jest.mocked(fetchChatFile).mockResolvedValue(response);
  render(
    <PublishedFilesGrid
      files={[{ ...file("file-11", "huge.md", null), mime_type: "" }]}
      unseenFileIds={[]}
      emptyLabel="No files"
      onOpen={jest.fn()}
    />
  );

  const tile = screen.getByRole("button", { name: "Open huge.md" });
  await waitFor(() => expect(fetchChatFile).toHaveBeenCalled());
  // The load settled once the tile's loading placeholder goes
  await waitFor(() =>
    expect(tile.querySelector("[inert] > .bg-background-neutral-02")).toBeNull()
  );
  expect(tile).not.toHaveTextContent("Hidden");
  expect(tile.querySelector("svg")).not.toBeNull();
  expect(fetchChatFile).toHaveBeenCalledWith("file-11", false, undefined);
});

test("a document tile shows its published thumbnail, else its icon", () => {
  const report = {
    ...file("file-8", "report.pdf", null),
    mime_type: "application/pdf",
    thumbnail_file_id: "thumbnail-8",
  };
  const deck = { ...file("file-9", "deck.pptx", null), mime_type: "" };
  render(
    <PublishedFilesGrid
      files={[report, deck]}
      unseenFileIds={[]}
      emptyLabel="No files"
      onOpen={jest.fn()}
    />
  );

  const reportTile = screen.getByRole("button", { name: "Open report.pdf" });
  const thumbnail = reportTile.querySelector("img");
  expect(thumbnail).toHaveAttribute("src", "/api/chat/file/thumbnail-8");
  expect(thumbnail).toHaveAttribute("loading", "lazy");
  // A file without a thumbnail shows its icon and loads nothing
  const deckTile = screen.getByRole("button", { name: "Open deck.pptx" });
  expect(deckTile.querySelector("img")).toBeNull();
  expect(deckTile.querySelector("svg")).not.toBeNull();
  expect(fetchChatFile).not.toHaveBeenCalled();

  // A thumbnail that fails to load falls back to the icon
  act(() => {
    thumbnail?.dispatchEvent(new Event("error"));
  });
  expect(reportTile.querySelector("img")).toBeNull();
  expect(reportTile.querySelector("svg")).not.toBeNull();
});

test("a text tile whose preview fails loads nothing again when it mounts again", async () => {
  observeAllInView();
  const fetchFile = jest
    .mocked(fetchChatFile)
    .mockRejectedValue(new Error("The file does not load"));
  const grid = (
    <PublishedFilesGrid
      files={[{ ...file("file-10", "notes.md", null), mime_type: "" }]}
      unseenFileIds={[]}
      emptyLabel="No files"
      onOpen={jest.fn()}
    />
  );
  const view = render(grid);
  await waitFor(() => expect(fetchFile).toHaveBeenCalledTimes(1));

  // A tile that mounts again, as on a later visit to the Files tab, keeps
  // its icon and fetches nothing
  view.rerender(<></>);
  view.rerender(grid);
  const tile = screen.getByRole("button", { name: "Open notes.md" });
  await waitFor(() => expect(tile.querySelector("svg")).not.toBeNull());
  expect(tile.querySelector("img")).toBeNull();
  expect(fetchFile).toHaveBeenCalledTimes(1);
});
