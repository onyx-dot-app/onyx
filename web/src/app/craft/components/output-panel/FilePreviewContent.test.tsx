import { Blob as NodeBlob } from "node:buffer";
import type { State } from "swr";
import { render, screen, waitFor } from "@tests/setup/test-utils";

import { FilePreviewContent } from "@/app/craft/components/output-panel/FilePreviewContent";
import { fetchFileContent } from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchFileContent: jest.fn(),
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

const mockPdfDestroy = jest.fn().mockResolvedValue(undefined);
const mockPdfGetDocument = jest.fn(() => ({
  promise: Promise.resolve({ numPages: 2 }),
  destroy: mockPdfDestroy,
}));
const mockPdfEvents = new Map<string, () => void>();

jest.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  AnnotationMode: { ENABLE: 1 },
  getDocument: () => mockPdfGetDocument(),
}));
jest.mock("pdfjs-dist/web/pdf_viewer.mjs", () => ({
  EventBus: jest.fn().mockImplementation(() => ({
    on: (name: string, callback: () => void) =>
      mockPdfEvents.set(name, callback),
  })),
  PDFLinkService: jest.fn().mockImplementation(() => ({
    setViewer: jest.fn(),
    setDocument: jest.fn(),
  })),
  LinkTarget: { BLANK: 2 },
  PDFViewer: jest.fn().mockImplementation(() => ({
    currentScaleValue: "",
    setDocument: (document: object | null) => {
      if (document) mockPdfEvents.get("pagesinit")?.();
    },
  })),
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

  it("forwards inline revisions to standalone previews", () => {
    render(
      <FilePreviewContent
        fullHeight={false}
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

  it.each(["revision", "reload"])(
    "reloads inline text after %s",
    async (change) => {
      jest.mocked(fetchFileContent).mockResolvedValue({
        content: "old text",
        mimeType: "text/plain",
        isImage: false,
      });
      const { rerender } = render(
        <FilePreviewContent
          fullHeight={false}
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
          fullHeight={false}
          sessionId="inline-text"
          filePath="outputs/notes.txt"
          revision={change === "revision" ? "456:100" : "123:100"}
          refreshKey={change === "reload" ? 1 : 0}
        />
      );
      await waitFor(() =>
        expect(screen.getByText("new text")).toBeInTheDocument()
      );
    }
  );

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

it("defers hidden PDF edits, retains its document, and releases bytes on eviction", async () => {
  const originalBlob = globalThis.Blob;
  Object.defineProperty(globalThis, "Blob", {
    configurable: true,
    writable: true,
    value: NodeBlob,
  });
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
    await screen.findByText("Page 1 of 2");
    const region = screen.getByRole("region", { name: "report.pdf" });
    rerender(view("2", false));
    rerender(view("3", false, 1));
    expect(screen.getByRole("region", { name: "report.pdf" })).toBe(region);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(mockPdfGetDocument).toHaveBeenCalledTimes(1);
    expect(mockPdfDestroy).not.toHaveBeenCalled();
    rerender(view("3", true, 1));
    await waitFor(() => expect(mockPdfGetDocument).toHaveBeenCalledTimes(2));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(globalCache.size).toBe(0);
    expect(mockPdfDestroy).toHaveBeenCalledTimes(1);
    unmount();
    expect(mockPdfDestroy).toHaveBeenCalledTimes(2);

    const reopened = render(view("3", true, 1));
    await screen.findByText("Page 1 of 2");
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(mockPdfGetDocument).toHaveBeenCalledTimes(3);
    reopened.unmount();
  } finally {
    fetch.mockRestore();
    globalThis.Blob = originalBlob;
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
