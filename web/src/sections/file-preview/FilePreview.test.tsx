import { useEffect, type ReactNode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { fileResponse } from "@tests/setup/fileResponse";
import { fetchChatFile } from "@/lib/chat/svc";
import { FetchError } from "@/lib/fetcher";
import { useChatFilePreview } from "@/lib/filePreview/hooks";
import {
  FilePreviewBody,
  FilePreviewScope,
} from "@/sections/file-preview/FilePreview";
import { CodeFilePreview } from "@/sections/file-preview/CodeFilePreview";

jest.mock("@/lib/chat/svc", () => ({
  fetchChatFile: jest.fn(),
}));

interface MockPdfPage {
  getViewport: (params: { scale: number }) => { width: number; height: number };
}

const mockPdfLoad: {
  fail: boolean;
  pageFail: "load" | "render" | null;
  // Each page's width and height; a page not listed is US Letter
  pageSizes: Record<number, [number, number]>;
  // Settles before the document returns a page
  pageReady: Promise<void>;
} = {
  fail: false,
  pageFail: null,
  pageSizes: {},
  pageReady: Promise.resolve(),
};

function mockPdfPage(pageNumber: number): MockPdfPage {
  const [width, height] = mockPdfLoad.pageSizes[pageNumber] ?? [612, 792];
  return { getViewport: () => ({ width, height }) };
}

jest.mock("react-pdf", () => ({
  pdfjs: { version: "test", GlobalWorkerOptions: {} },
  Document: ({
    children,
    onLoadSuccess,
    onLoadError,
  }: {
    children: ReactNode;
    onLoadSuccess: (pdf: {
      numPages: number;
      getPage: (pageNumber: number) => Promise<MockPdfPage>;
    }) => void;
    onLoadError: () => void;
  }) => {
    useEffect(() => {
      if (mockPdfLoad.fail) onLoadError();
      else
        onLoadSuccess({
          numPages: 3,
          getPage: async (pageNumber) => {
            await mockPdfLoad.pageReady;
            return mockPdfPage(pageNumber);
          },
        });
    }, []);
    return <div>{children}</div>;
  },
  Page: ({
    pageNumber,
    scale,
    onLoadSuccess,
    onLoadError,
    onRenderError,
  }: {
    pageNumber: number;
    scale?: number;
    onLoadSuccess?: (page: MockPdfPage) => void;
    onLoadError?: (error: Error) => void;
    onRenderError?: (error: Error) => void;
  }) => {
    useEffect(() => {
      if (mockPdfLoad.pageFail === null)
        onLoadSuccess?.(mockPdfPage(pageNumber));
      if (scale === undefined) return;
      if (mockPdfLoad.pageFail === "load") onLoadError?.(new Error("load"));
      if (mockPdfLoad.pageFail === "render")
        onRenderError?.(new Error("render"));
    }, []);
    return (
      <div
        data-testid={scale === undefined ? "thumbnail" : "pdf-page"}
        data-page={pageNumber}
      />
    );
  },
}));

const FILE_URL = "/api/chat/file/file-1";

function PreviewOf({ name }: { name: string }) {
  const preview = useChatFilePreview("file-1", name);
  return <FilePreviewBody preview={preview} fileName={name} />;
}

function renderPreview(name: string) {
  return render(
    <FilePreviewScope>
      <PreviewOf name={name} />
    </FilePreviewScope>
  );
}

function expectDownloadLink(name: string, fileName: string) {
  const link = screen.getByRole("link", { name });
  expect(link).toHaveAttribute("href", FILE_URL);
  expect(link).toHaveAttribute("download", fileName);
  // The link is the button: one tab stop, no control nested in it.
  expect(within(link).queryByRole("button")).toBeNull();
}

/** A file that cannot show shows one card, with the only download. */
function expectUnavailableCard(
  fileName: string,
  title = "Cannot preview this file"
) {
  expect(screen.getByText(title)).toBeVisible();
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expectDownloadLink("Download File", fileName);
}

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.scrollTo = jest.fn();
  Element.prototype.checkVisibility = jest.fn(() => true);
});

beforeEach(() => {
  mockPdfLoad.fail = false;
  mockPdfLoad.pageFail = null;
  mockPdfLoad.pageSizes = {};
  mockPdfLoad.pageReady = Promise.resolve();
});

describe("loading and failure", () => {
  test("shows a loader when the file is slow to load, until it loads", async () => {
    let respond: (response: Response) => void = () => undefined;
    jest.mocked(fetchChatFile).mockReturnValue(
      new Promise((resolve) => {
        respond = resolve;
      })
    );
    renderPreview("notes.txt");

    // A fast load shows no loader
    expect(screen.queryByRole("status", { name: "Loading" })).toBeNull();
    expect(
      await screen.findByRole("status", { name: "Loading" })
    ).toBeVisible();
    expect(
      screen.queryByText("Preparing the preview. This can take a little while.")
    ).toBeNull();
    await act(async () =>
      respond(fileResponse("hello", "text/plain", "notes.txt"))
    );
    expect(await screen.findByText("hello")).toBeVisible();
    expect(screen.queryByRole("status", { name: "Loading" })).toBeNull();
  });

  test("a Word or PowerPoint file says that its preview is being prepared", async () => {
    jest.mocked(fetchChatFile).mockReturnValue(new Promise(() => undefined));
    renderPreview("deck.pptx");

    const status = await screen.findByText(
      "Preparing the preview. This can take a little while."
    );
    expect(status).toBeVisible();
    expect(status.closest("[aria-live]")).toHaveAttribute(
      "aria-live",
      "polite"
    );
  });

  test("a failed load offers the download and a retry that loads again", async () => {
    jest
      .mocked(fetchChatFile)
      .mockRejectedValueOnce(new Error("Failed to load document."))
      .mockResolvedValueOnce(fileResponse("hello", "text/plain", "notes.txt"));
    renderPreview("notes.txt");

    expect(await screen.findByText("Unable to load preview")).toBeVisible();
    expectDownloadLink("Download File", "notes.txt");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("hello")).toBeVisible();
  });

  test("a preview that closes stops its download", async () => {
    jest.useFakeTimers();
    try {
      jest.mocked(fetchChatFile).mockReturnValue(new Promise(() => undefined));
      const view = renderPreview("notes.txt");
      await waitFor(() => expect(fetchChatFile).toHaveBeenCalled());
      const signal = jest.mocked(fetchChatFile).mock.calls[0]?.[2];

      expect(signal?.aborted).toBe(false);
      view.unmount();
      act(() => jest.runOnlyPendingTimers());
      expect(signal?.aborted).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("text formats", () => {
  test("code shows highlighted source, line numbers, its line count, copy and download", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("const a = 1;\n", "text/javascript", "main.js")
      );
    const view = renderPreview("main.js");

    expect(await screen.findByText("2 lines")).toBeVisible();
    expect(view.container.querySelector("code")).toHaveTextContent(
      "const a = 1;"
    );
    expect(view.container.querySelector("pre[aria-hidden]")?.textContent).toBe(
      "1\n2"
    );
    expect(screen.getByRole("button", { name: "Copy content" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show source" })).toBeNull();
    expectDownloadLink("Download", "main.js");
    await waitFor(() =>
      expect(view.container.querySelector("code .hljs-keyword")).not.toBeNull()
    );
  });

  test("HTML renders in a sandboxed frame that sends no requests, and toggles to its source", async () => {
    const html =
      '<html><head><title>Q3</title></head><body><h1 class="x">Report</h1></body></html>\n';
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse(html, "text/html", "page.html"));
    const view = renderPreview("page.html");

    const frame = await screen.findByTitle("page.html");
    expect(frame).toHaveAttribute("sandbox", "");
    // A fixed prologue carries the policy; the page follows unchanged
    const srcdoc = frame.getAttribute("srcdoc") ?? "";
    expect(srcdoc).toMatch(
      /^<!DOCTYPE html><meta http-equiv="Content-Security-Policy" content="default-src 'none';[^"]*form-action 'none'">/
    );
    expect(srcdoc.replace(/^<!DOCTYPE html><meta [^>]*>/, "")).toBe(html);
    // No script runs and nothing loads from the network, so the page cannot
    // send its contents out
    const prologue = srcdoc.match(/^<!DOCTYPE html><meta [^>]*>/)?.[0];
    expect(prologue).toContain("script-src 'none'");
    expect(prologue).not.toMatch(/https?:/);
    // The parser applies the policy whatever head-like text the file has
    const parsed = new DOMParser().parseFromString(
      srcdoc.replace(html, "<!-- <head> --><script>fetch('/x')</script>"),
      "text/html"
    );
    expect(
      parsed.head.querySelector('meta[http-equiv="Content-Security-Policy"]')
    ).not.toBeNull();
    expectDownloadLink("Download", "page.html");

    fireEvent.click(screen.getByRole("button", { name: "Show source" }));
    expect(view.container.querySelector("iframe")).toBeNull();
    expect(view.container.querySelector("code")).toHaveTextContent(
      '<h1 class="x">Report</h1>'
    );
    expect(screen.getByText("2 lines")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show source" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show preview" }));
    expect(view.container.querySelector("iframe")).not.toBeNull();
  });

  test("SVG renders as an image and toggles to its source", async () => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="4"/></svg>';
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse(svg, "image/svg+xml", "logo.svg"));
    const view = renderPreview("logo.svg");

    const image = await screen.findByRole("img", { name: "logo.svg" });
    expect(image).toHaveAttribute(
      "src",
      `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
    );

    fireEvent.click(screen.getByRole("button", { name: "Show source" }));
    expect(screen.queryByRole("img", { name: "logo.svg" })).toBeNull();
    expect(view.container.querySelector("code")).toHaveTextContent("<circle");
  });

  test("an SVG the browser cannot draw shows its source", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("<svg><broken", "image/svg+xml", "bad.svg")
      );
    const view = renderPreview("bad.svg");

    fireEvent.error(await screen.findByRole("img", { name: "bad.svg" }));
    expect(view.container.querySelector("code")).toHaveTextContent(
      "<svg><broken"
    );
    expect(screen.getByRole("button", { name: "Copy content" })).toBeVisible();
  });

  test("JSON indented past the highlight limit shows plain", async () => {
    // Compact, the JSON fits the limit; indented, it does not
    const json = JSON.stringify(
      Array.from({ length: 15_000 }, (_, index) => ({ k: index }))
    );
    expect(json.length).toBeLessThan(200_000);
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse(json, "application/json", "big.json"));
    const view = renderPreview("big.json");

    await waitFor(() =>
      expect(view.container.querySelector("code")?.textContent).toContain(
        '\n    "k": 0\n'
      )
    );
    // The small file loads the grammars, which the large one must not use
    const small = render(<CodeFilePreview text='{"a":1}' language="json" />);
    await waitFor(() =>
      expect(small.container.querySelector("code span")).not.toBeNull()
    );
    expect(view.container.querySelector("code span")).toBeNull();
  });

  test("JSON shows indented", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse('{"a":{"b":1}}', "application/json", "data.json")
      );
    const view = renderPreview("data.json");

    await waitFor(() =>
      expect(view.container.querySelector("code")?.textContent).toBe(
        '{\n  "a": {\n    "b": 1\n  }\n}'
      )
    );
  });

  test("markdown shows as a document without its raw HTML", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "# Q3\n\nSee [Onyx](https://onyx.app).\n\n<script>alert(1)</script>\n",
          "text/markdown",
          "notes.md"
        )
      );
    const view = renderPreview("notes.md");

    expect(
      await screen.findByRole("heading", { name: "Q3" })
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Onyx" })).toHaveAttribute(
      "target",
      "_blank"
    );
    expect(view.container.querySelector("script")).toBeNull();
    expectDownloadLink("Download", "notes.md");

    fireEvent.click(screen.getByRole("button", { name: "Show source" }));
    expect(screen.queryByRole("heading", { name: "Q3" })).toBeNull();
    expect(view.container.querySelector("code")?.textContent).toMatch(/^# Q3/);
  });

  test("markdown highlights its tagged fenced code and leaves untagged code plain", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "# Setup\n\n```python\ndef run():\n    return 1\n```\n\n```\nSELECT id FROM users WHERE id = 1;\n```\n",
          "text/markdown",
          "setup.md"
        )
      );
    const view = renderPreview("setup.md");

    expect(
      await screen.findByRole("heading", { name: "Setup" })
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(view.container.querySelector("code .hljs-keyword")).not.toBeNull()
    );
    // Guessing a language for large untagged blocks can freeze the tab
    const untagged = screen.getByText("SELECT id FROM users WHERE id = 1;", {
      exact: false,
    });
    expect(
      untagged.closest("code")?.querySelector("[class^=hljs-]")
    ).toBeNull();
  });

  test("markdown links with a scheme or www. open their site; other links show as text", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "See [site](https://onyx.app), [mail](mailto:team@onyx.app), [www](www.onyx.app), [guide](guide.md) and [setup](docs/setup.md).\n",
          "text/markdown",
          "links.md"
        )
      );
    renderPreview("links.md");

    await waitFor(() =>
      expect(screen.getByRole("link", { name: "site" })).toHaveAttribute(
        "href",
        "https://onyx.app"
      )
    );
    const site = screen.getByRole("link", { name: "site" });
    expect(site).toHaveAttribute("target", "_blank");
    expect(site).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: "mail" })).toHaveAttribute(
      "href",
      "mailto:team@onyx.app"
    );
    const www = screen.getByRole("link", { name: "www" });
    expect(www).toHaveAttribute("href", "https://www.onyx.app");
    expect(www).toHaveAttribute("rel", "noopener noreferrer");
    // A relative link has no target outside the file: its text stays
    expect(screen.queryByRole("link", { name: "guide" })).toBeNull();
    expect(screen.queryByRole("link", { name: "setup" })).toBeNull();
    expect(
      screen.getByRole("link", { name: "site" }).parentElement
    ).toHaveTextContent("See site, mail, www, guide and setup.");
  });

  test("long markdown shows as source", async () => {
    const text = `# Big\n\n${"word ".repeat(50_000)}`;
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse(text, "text/markdown", "big.md"));
    const view = renderPreview("big.md");

    await waitFor(() =>
      expect(view.container.querySelector("code")?.textContent).toMatch(
        /^# Big/
      )
    );
    expect(screen.queryByRole("heading", { name: "Big" })).toBeNull();
  });

  test("a CSV shows quoted fields whole in a grid", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          'Region,Owner\nNorth,"Smith, Jane"\nEast,"Multi\nline"\n',
          "text/csv",
          "sales.csv"
        )
      );
    renderPreview("sales.csv");

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(2);
    expect(within(table).getByText("Smith, Jane")).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expectDownloadLink("Download", "sales.csv");

    fireEvent.click(screen.getByRole("button", { name: "Show source" }));
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText(/North,"Smith, Jane"/)).toBeInTheDocument();
  });

  test("a CSV keeps an empty last record and fills a short row with one cell", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("Region,Owner,Notes\nNorth\n\n", "text/csv", "short.csv")
      );
    renderPreview("short.csv");

    const table = await screen.findByRole("table");
    const [, short, empty] = within(table).getAllByRole("row");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    // The gap cell is hidden from assistive technology
    const shortCells = within(short!).getAllByRole("cell", { hidden: true });
    expect(shortCells).toHaveLength(2);
    expect(shortCells[0]).toHaveTextContent("North");
    expect(shortCells[1]).toHaveAttribute("colspan", "2");
    expect(within(empty!).getAllByRole("cell", { hidden: true })).toHaveLength(
      2
    );
  });

  test("a malformed CSV says so", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse('a,b\n1,"open\n', "text/csv", "bad.csv"));
    renderPreview("bad.csv");

    expect(
      await screen.findByText(/This CSV contains an invalid quoted field/)
    ).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("documents", () => {
  test("a workbook shows its parsed sheets with a sheet bar", async () => {
    jest.mocked(fetchChatFile).mockResolvedValue(
      new Response(
        JSON.stringify({
          sheets: [
            { name: "Summary", csv: "Region\nNorth\n", truncated: false },
            { name: "Detail", csv: "Month\nJuly\n", truncated: true },
          ],
        }),
        { headers: { "Content-Type": "application/json" } }
      )
    );
    renderPreview("book.xlsx");

    expect(await screen.findByText("North")).toBeVisible();
    expect(fetchChatFile).toHaveBeenCalledWith(
      "file-1",
      "parsed",
      expect.any(AbortSignal)
    );
    fireEvent.click(screen.getByRole("button", { name: "Detail" }));
    expect(screen.getByText("July")).toBeVisible();
    expect(screen.getByRole("button", { name: "Detail" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    expect(screen.getByText(/Preview limited to/)).toBeVisible();
    expectDownloadLink("Download", "book.xlsx");
  });

  test("a PDF shows its pages with page controls and a download", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("%PDF-1.4", "application/pdf", "report.pdf")
      );
    renderPreview("report.pdf");

    expect(await screen.findByText("1 / 3")).toBeVisible();
    expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "1");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("2 / 3")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Go to page 3" }));
    expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "3");
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    // One tab stop: the current page. Focus follows the arrow keys.
    const third = screen.getByRole("button", { name: "Go to page 3" });
    expect(third).toHaveAttribute("tabindex", "0");
    expect(
      screen.getByRole("button", { name: "Go to page 1" })
    ).toHaveAttribute("tabindex", "-1");
    act(() => third.focus());
    fireEvent.keyDown(third, { key: "ArrowUp" });
    expect(screen.getByText("2 / 3")).toBeVisible();
    expect(screen.getByRole("button", { name: "Go to page 2" })).toHaveFocus();
    expectDownloadLink("Download", "report.pdf");
  });

  test("a PDF shows the loader until its first page loads", async () => {
    let firstPageReady: () => void = () => undefined;
    mockPdfLoad.pageReady = new Promise((resolve) => {
      firstPageReady = resolve;
    });
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("%PDF-1.4", "application/pdf", "report.pdf")
      );
    renderPreview("report.pdf");

    expect(
      await screen.findByRole("status", { name: "Loading" })
    ).toBeVisible();
    expect(screen.queryByText("1 / 3")).toBeNull();
    await act(async () => firstPageReady());
    expect(await screen.findByText("1 / 3")).toBeVisible();
    expect(screen.queryByRole("status", { name: "Loading" })).toBeNull();
  });

  test("a PDF that does not open offers one download", async () => {
    mockPdfLoad.fail = true;
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("broken", "application/pdf", "bad.pdf"));
    renderPreview("bad.pdf");

    await screen.findByText("Cannot preview this file");
    expectUnavailableCard("bad.pdf");
  });

  test.each(["load", "render"] as const)(
    "a PDF page that fails to %s offers one download",
    async (failure) => {
      mockPdfLoad.pageFail = failure;
      jest
        .mocked(fetchChatFile)
        .mockResolvedValue(
          fileResponse("%PDF-1.4", "application/pdf", "bad-page.pdf")
        );
      renderPreview("bad-page.pdf");

      await screen.findByText("Cannot preview this file");
      expectUnavailableCard("bad-page.pdf");
    }
  );

  test("a deck shows as the PDF pages that the server converts it to, and downloads the original", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("%PDF-1.4", "application/pdf", "preview.pdf")
      );
    renderPreview("deck.pptx");

    expect(await screen.findByText("1 / 3")).toBeVisible();
    expectDownloadLink("Download", "deck.pptx");
  });

  test("a deck that the server cannot convert offers one download and no retry", async () => {
    jest.mocked(fetchChatFile).mockRejectedValue(
      new FetchError("Failed to load document.", 422, {
        error_code: "PREVIEW_UNAVAILABLE",
        detail: "No preview",
      })
    );
    renderPreview("deck.pptx");

    await screen.findByText("No preview for this file");
    expectUnavailableCard("deck.pptx", "No preview for this file");
    expect(
      screen.getByText(
        "A preview of this file cannot be made. Download the file to open it."
      )
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });

  test("a thumbnail takes its page's shape: the first page's until it loads its own", async () => {
    mockPdfLoad.pageSizes = { 1: [1280, 720], 2: [612, 792] };
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("%PDF-1.4", "application/pdf", "slides.pdf")
      );
    renderPreview("slides.pdf");

    await screen.findByText("1 / 3");
    const box = (page: number) =>
      screen.getByRole("button", { name: `Go to page ${page}` })
        .firstElementChild?.firstElementChild;
    // A landscape slide gets a landscape box, and so does a page that has
    // not loaded its own shape
    expect(box(1)).toHaveStyle({ aspectRatio: String(1280 / 720) });
    expect(box(2)).toHaveStyle({ aspectRatio: String(1280 / 720) });
    // A page of another size gets its own shape once it loads, and keeps it
    // when its drawing is dropped
    fireEvent.click(screen.getByRole("button", { name: "Go to page 2" }));
    expect(box(2)).toHaveStyle({ aspectRatio: String(612 / 792) });
    fireEvent.click(screen.getByRole("button", { name: "Go to page 3" }));
    expect(box(2)?.childElementCount).toBe(0);
    expect(box(2)).toHaveStyle({ aspectRatio: String(612 / 792) });
  });

  /** Observed elements, each resized through its observer's callback. */
  function observeResizes() {
    const observed = new Map<Element, ResizeObserverCallback>();
    jest.spyOn(global, "ResizeObserver").mockImplementation(
      (callback) =>
        ({
          observe: (element: Element) => observed.set(element, callback),
          unobserve: (element: Element) => observed.delete(element),
          disconnect: () => undefined,
        }) as unknown as ResizeObserver
    );
    return observed;
  }

  async function renderPdf() {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse("%PDF-1.4", "application/pdf", "report.pdf")
      );
    renderPreview("report.pdf");
    await screen.findByText("1 / 3");
  }

  const separator = () =>
    screen.queryByRole("separator", { name: "Resize page thumbnails" });

  test("a PDF's thumbnail column follows the width of the row that holds it, and keeps its state at width 0", async () => {
    const observed = observeResizes();
    try {
      await renderPdf();
      const column = separator();
      if (!column) throw new Error("the column shows before a measurement");
      // The observed row holds the column and its resize separator
      const [row, resized] =
        Array.from(observed).find(([element]) => element.contains(column)) ??
        [];
      if (!row || !resized) throw new Error("no observed row holds the column");
      const resize = (width: number) =>
        act(() =>
          resized(
            [{ contentRect: { width } } as ResizeObserverEntry],
            {} as ResizeObserver
          )
        );

      // A phone-width preview
      resize(389);
      expect(separator()).not.toBeInTheDocument();
      // A hidden tab reports width 0
      resize(0);
      expect(separator()).not.toBeInTheDocument();
      // A rotation to a wide preview shows them
      resize(800);
      expect(separator()).toBeInTheDocument();
      resize(0);
      expect(separator()).toBeInTheDocument();

      fireEvent.click(
        screen.getByRole("button", { name: "Toggle page thumbnails" })
      );
      expect(separator()).not.toBeInTheDocument();
      // The toggle wins over a later width
      resize(900);
      expect(separator()).not.toBeInTheDocument();
    } finally {
      jest.restoreAllMocks();
    }
  });

  test("a PDF on a phone-width preview mounts without its thumbnail column", async () => {
    // The observer never reports: the row's width comes from its mount
    observeResizes();
    jest
      .spyOn(HTMLElement.prototype, "clientWidth", "get")
      .mockReturnValue(390);
    try {
      await renderPdf();
      expect(separator()).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Toggle page thumbnails" })
      ).toHaveAttribute("aria-pressed", "false");
    } finally {
      jest.restoreAllMocks();
    }
  });
});

describe("images and other files", () => {
  test("an image loads from the file URL and toggles its actual size", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("png", "image/png", "chart.png"));
    renderPreview("chart.png");

    const image = await screen.findByRole("img", { name: "chart.png" });
    expect(image).toHaveAttribute("src", FILE_URL);
    expect(screen.getByText("Loading image...")).toBeInTheDocument();
    fireEvent.load(image);
    const toggle = screen.getByRole("button", { name: "Actual size" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(image).toHaveClass("max-w-none");
    expectDownloadLink("Download", "chart.png");
  });

  test("an image the browser cannot draw offers one download", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("heic", "image/heic", "photo.heic"));
    renderPreview("photo.heic");

    fireEvent.error(await screen.findByRole("img", { name: "photo.heic" }));
    expectUnavailableCard("photo.heic");
  });

  test("an unsupported file offers the download", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("zip", "application/zip", "archive.zip"));
    renderPreview("archive.zip");

    expect(
      await screen.findByText(
        "Preview for this file type is not currently supported"
      )
    ).toBeVisible();
    expectDownloadLink("Download File", "archive.zip");
  });

  test("a file over the limit offers the download", async () => {
    const response = fileResponse("x", "text/plain", "huge.log");
    response.headers.set("Content-Length", String(6 * 1024 * 1024));
    jest.mocked(fetchChatFile).mockResolvedValue(response);
    renderPreview("huge.log");

    expect(await screen.findByText("File too large to preview")).toBeVisible();
    expect(screen.getByText(/Files up to 5 MB/)).toBeVisible();
    expectDownloadLink("Download File", "huge.log");
  });
});
