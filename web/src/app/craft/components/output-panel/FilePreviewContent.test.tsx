import PdfDocumentViewer from "@/app/craft/components/output-panel/PdfDocumentViewer";
import type { State } from "swr";
import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";

import { FilePreviewContent } from "@/app/craft/components/output-panel/FilePreviewContent";
import {
  downloadArtifactFile,
  fetchFileContent,
} from "@/app/craft/services/apiServices";

let mockViewerUserId: string | undefined = "viewer-user";
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: mockViewerUserId ? { id: mockViewerUserId } : null }),
}));
beforeEach(() => {
  mockViewerUserId = "viewer-user";
});

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchFileContent: jest.fn(),
  downloadArtifactFile: jest.fn(),
}));

jest.mock("@/app/craft/components/output-panel/PptxPreview", () => ({
  __esModule: true,
  default: ({
    sessionId,
    filePath,
    revision,
    refreshKey,
  }: {
    sessionId: string;
    filePath: string;
    revision?: string;
    refreshKey?: number;
  }) => (
    <div
      data-revision={revision}
      data-refresh-key={refreshKey}
    >{`PowerPoint preview for ${filePath} in session ${sessionId}`}</div>
  ),
}));

jest.mock("@/app/craft/components/output-panel/PdfDocumentViewer", () => ({
  __esModule: true,
  default: jest.fn(({ blob }: { blob: Blob }) => (
    <div title="report.pdf" data-size={blob.size} />
  )),
}));

describe("FilePreviewContent", () => {
  beforeEach(() => {
    jest.mocked(fetchFileContent).mockReset();
  });

  it("routes a legacy .ppt file directly to the presentation renderer", () => {
    const filePath = "outputs/quarterly review.ppt";

    render(<FilePreviewContent sessionId="session-1" filePath={filePath} />);

    expect(
      screen.getByText(
        `PowerPoint preview for ${filePath} in session session-1`
      )
    ).toBeInTheDocument();
    expect(fetchFileContent).not.toHaveBeenCalled();
  });

  it("does not mistake a compound extension for a presentation", async () => {
    jest.mocked(fetchFileContent).mockResolvedValue({
      content: "plain text",
      mimeType: "text/plain",
      isImage: false,
    });

    render(
      <FilePreviewContent
        sessionId="session-1"
        filePath="outputs/notes.ppt.txt"
      />
    );

    expect(await screen.findByText("plain text")).toBeInTheDocument();
    expect(fetchFileContent).toHaveBeenCalledWith(
      "session-1",
      "outputs/notes.ppt.txt"
    );
  });

  it("forwards revisions to standalone previews", () => {
    render(
      <FilePreviewContent
        revision="123:100"
        sessionId="inline-slides"
        filePath="outputs/deck.pptx"
        refreshKey={3}
      />
    );
    expect(screen.getByText(/PowerPoint preview/)).toHaveAttribute(
      "data-refresh-key",
      "3"
    );
    expect(screen.getByText(/PowerPoint preview/)).toHaveAttribute(
      "data-revision",
      "123:100"
    );
  });

  it.each(["revision", "reload"])("reloads text after %s", async (change) => {
    jest.mocked(fetchFileContent).mockResolvedValue({
      content: "old text",
      mimeType: "text/plain",
      isImage: false,
    });
    const { rerender } = render(
      <FilePreviewContent
        sessionId="inline-text"
        filePath="outputs/notes.txt"
        revision="123:100"
        refreshKey={0}
      />
    );
    expect(await screen.findByText("old text")).toBeInTheDocument();
    jest.mocked(fetchFileContent).mockResolvedValue({
      content: "new text",
      mimeType: "text/plain",
      isImage: false,
    });
    rerender(
      <FilePreviewContent
        sessionId="inline-text"
        filePath="outputs/notes.txt"
        revision={change === "revision" ? "456:100" : "123:100"}
        refreshKey={change === "reload" ? 1 : 0}
      />
    );
    await waitFor(() =>
      expect(screen.getByText("new text")).toBeInTheDocument()
    );
  });

  it("uses detected image content before the Markdown extension", async () => {
    const content = "data:image/png;base64,aW1hZ2U=";
    jest.mocked(fetchFileContent).mockResolvedValue({
      content,
      mimeType: "image/png",
      isImage: true,
    });
    render(
      <FilePreviewContent
        sessionId="image-priority"
        filePath="outputs/image.md"
      />
    );
    expect(await screen.findByRole("img")).toHaveAttribute("src", content);
  });
});

it("defers hidden PDF edits and releases cached bytes on eviction", async () => {
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response("pdf"));
  const globalCache = new Map<string, State>();
  try {
    const view = (revision: string, isActive = true, refreshKey = 0) => (
      <FilePreviewContent
        sessionId="retained-pdf"
        filePath="outputs/report.pdf"
        revision={revision}
        isActive={isActive}
        refreshKey={refreshKey}
      />
    );
    const { rerender, unmount } = render(view("1"), {
      swrConfig: { provider: () => globalCache },
    });
    const body = await screen.findByTitle("report.pdf");
    const displayed = () =>
      jest.mocked(PdfDocumentViewer).mock.calls.at(-1)?.[0].blob;
    const originalBlob = displayed();
    rerender(view("2", false));
    rerender(view("3", false, 1));
    expect(screen.getByTitle("report.pdf")).toBe(body);
    expect(fetch).toHaveBeenCalledTimes(1);
    rerender(view("3", true, 1));
    await waitFor(() => expect(displayed()).not.toBe(originalBlob));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(globalCache.size).toBe(0);
    unmount();
    const reopened = render(view("3", true, 1));
    await screen.findByTitle("report.pdf");
    expect(fetch).toHaveBeenCalledTimes(3);
    reopened.unmount();
  } finally {
    fetch.mockRestore();
  }
});

it("coalesces hidden text edits to the latest revision", async () => {
  jest.mocked(fetchFileContent).mockReset().mockResolvedValue({
    content: "old",
    mimeType: "text/plain",
    isImage: false,
  });
  const view = (revision: string, isActive: boolean) => (
    <FilePreviewContent
      sessionId="retained-text"
      filePath="outputs/report.txt"
      revision={revision}
      isActive={isActive}
    />
  );
  const { rerender } = render(view("1", true));
  await screen.findByText("old");
  rerender(view("2", false));
  rerender(view("3", false));
  expect(screen.getByText("old")).toBeInTheDocument();
  expect(fetchFileContent).toHaveBeenCalledTimes(1);
  jest.mocked(fetchFileContent).mockResolvedValue({
    content: "latest",
    mimeType: "text/plain",
    isImage: false,
  });
  rerender(view("3", true));
  await screen.findByText("latest");
  expect(fetchFileContent).toHaveBeenCalledTimes(2);
});

it("revalidates retained source files on activation without resetting their scroll", async () => {
  jest.mocked(fetchFileContent).mockReset().mockResolvedValue({
    content: "original source",
    mimeType: "text/plain",
    isImage: false,
  });
  const view = (isActive: boolean) => (
    <FilePreviewContent
      sessionId="retained-source"
      filePath="web/src/app/page.tsx"
      isActive={isActive}
    />
  );
  const { rerender } = render(view(true));
  const source = await screen.findByText("original source");
  const scroller = source.parentElement;
  if (!scroller) throw new Error("Missing source scroll container");
  scroller.scrollTop = 120;
  rerender(view(false));
  expect(fetchFileContent).toHaveBeenCalledTimes(1);

  // Reopening an unchanged file must keep its DOM and scroll position.
  rerender(view(true));
  await waitFor(() => expect(fetchFileContent).toHaveBeenCalledTimes(2));
  expect(screen.getByText("original source")).toBe(source);
  expect(scroller.scrollTop).toBe(120);

  rerender(view(false));
  jest.mocked(fetchFileContent).mockResolvedValue({
    content: "updated source",
    mimeType: "text/plain",
    isImage: false,
  });
  rerender(view(true));
  await screen.findByText("updated source");
  expect(fetchFileContent).toHaveBeenCalledTimes(3);
  expect(screen.getByText("updated source")).toBe(source);
  expect(scroller.scrollTop).toBe(120);
});

it("restores a text viewer position after eviction and reports active scrolling", async () => {
  jest.mocked(fetchFileContent).mockResolvedValue({
    content: "Retained scroll content",
    mimeType: "text/plain",
    isImage: false,
  });
  const onScrollTopChange = jest.fn();
  const view = (initialScrollTop: number) => (
    <FilePreviewContent
      sessionId="scroll-restoration"
      filePath="outputs/notes.txt"
      initialScrollTop={initialScrollTop}
      onScrollTopChange={onScrollTopChange}
    />
  );
  const { unmount } = render(view(140));
  let text = await screen.findByText("Retained scroll content");
  let scroll = text.closest(".overflow-auto");
  if (!scroll) throw new Error("No viewer scroll region");
  expect(scroll.scrollTop).toBe(140);
  fireEvent.scroll(scroll, { target: { scrollTop: 220 } });
  expect(onScrollTopChange).toHaveBeenLastCalledWith(220);
  unmount();
  render(view(220));
  text = await screen.findByText("Retained scroll content");
  scroll = text.closest(".overflow-auto");
  expect(scroll?.scrollTop).toBe(220);
});

// Unsupported preview download
it("offers a download for unsupported content", async () => {
  jest.mocked(fetchFileContent).mockResolvedValue({
    content: "",
    mimeType: "application/octet-stream",
    error: "unsupported_binary",
  });
  render(
    <FilePreviewContent
      sessionId="session-download"
      filePath="outputs/archive.zip"
    />
  );
  fireEvent.click(await screen.findByRole("button", { name: "Download" }));
  expect(downloadArtifactFile).toHaveBeenCalledWith(
    "session-download",
    "outputs/archive.zip"
  );
});

it.each(["png", "md"])(
  "shows refresh progress and errors over retained %s previews",
  async (extension) => {
    const original = {
      content:
        extension === "png" ? "data:image/png;base64,abc" : "retained markdown",
      mimeType: extension === "png" ? "image/png" : "text/markdown",
      isImage: extension === "png",
    };
    const refresh = deferred<typeof original>();
    jest
      .mocked(fetchFileContent)
      .mockReset()
      .mockResolvedValueOnce(original)
      .mockReturnValueOnce(refresh.promise);
    const onRefreshingChange = jest.fn();
    const props = {
      onRefreshingChange,
      sessionId: `feedback-${extension}`,
      filePath: `outputs/file.${extension}`,
      revision: "original",
    };
    const { rerender } = render(
      <FilePreviewContent {...props} refreshKey={0} />
    );
    await waitFor(() => expect(fetchFileContent).toHaveBeenCalledTimes(1));
    if (extension === "png")
      expect(await screen.findByRole("img")).toBeInTheDocument();
    else
      expect(await screen.findByText("retained markdown")).toBeInTheDocument();
    rerender(<FilePreviewContent {...props} refreshKey={1} />);
    expect(onRefreshingChange).toHaveBeenLastCalledWith(true);
    await act(async () => refresh.reject(new Error("refresh failed")));
    expect(screen.getByRole("alert")).toHaveTextContent("refresh failed");
    if (extension === "png")
      expect(screen.getByRole("img")).toBeInTheDocument();
    else expect(screen.getByText("retained markdown")).toBeInTheDocument();
  }
);

// Authentication ownership
it("waits for authenticated identity and releases private bytes on user changes", async () => {
  mockViewerUserId = undefined;
  jest.mocked(fetchFileContent).mockReset().mockResolvedValue({
    content: "first user's file",
    mimeType: "text/plain",
  });
  const view = () => (
    <FilePreviewContent
      sessionId="same-session"
      filePath="outputs/readme.txt"
      revision="same-revision"
    />
  );
  const { rerender } = render(view());
  expect(fetchFileContent).not.toHaveBeenCalled();
  mockViewerUserId = "first-user";
  rerender(view());
  await screen.findByText("first user's file");
  const secondRead = deferred<{ content: string; mimeType: string }>();
  jest.mocked(fetchFileContent).mockReturnValueOnce(secondRead.promise);
  mockViewerUserId = "second-user";
  rerender(view());
  expect(screen.queryByText("first user's file")).not.toBeInTheDocument();
  await act(async () => {
    secondRead.resolve({
      content: "second user's file",
      mimeType: "text/plain",
    });
  });
  await screen.findByText("second user's file");
  expect(fetchFileContent).toHaveBeenCalledTimes(2);
});

// Preview lifetime and rendering.
it("renders CSV content as a table through the file preview", async () => {
  jest.mocked(fetchFileContent).mockResolvedValue({
    content: "name,value\nAlice,42",
    mimeType: "text/csv",
    isImage: false,
  });
  render(
    <FilePreviewContent sessionId="csv-session" filePath="outputs/data.csv" />
  );
  expect(
    await screen.findByRole("columnheader", { name: "name" })
  ).toBeInTheDocument();
  expect(screen.getByRole("cell", { name: "Alice" })).toBeInTheDocument();
});
