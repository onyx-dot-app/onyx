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
import { renderDocx } from "@/lib/docx/renderDocx";
import { pptxToHtml } from "@jvmr/pptx-to-html";
import { useChatFilePreview } from "@/lib/filePreview/hooks";
import {
  FilePreviewBody,
  FilePreviewScope,
} from "@/sections/file-preview/FilePreview";
import { CodeFilePreview } from "@/sections/file-preview/CodeFilePreview";

jest.mock("@/lib/chat/svc", () => ({
  fetchChatFile: jest.fn(),
}));

jest.mock("@/lib/docx/renderDocx", () => ({
  renderDocx: jest.fn(),
}));

// jsdom cannot run the parser's namespaced selectors; the tests give its
// slide markup
jest.mock("@jvmr/pptx-to-html", () => ({
  pptxToHtml: jest.fn(),
}));

const mockPdfLoad: { fail: boolean; pageFail: "load" | "render" | null } = {
  fail: false,
  pageFail: null,
};
jest.mock("react-pdf", () => ({
  pdfjs: { version: "test", GlobalWorkerOptions: {} },
  Document: ({
    children,
    onLoadSuccess,
    onLoadError,
  }: {
    children: ReactNode;
    onLoadSuccess: (pdf: { numPages: number }) => void;
    onLoadError: () => void;
  }) => {
    useEffect(() => {
      if (mockPdfLoad.fail) onLoadError();
      else onLoadSuccess({ numPages: 3 });
    }, []);
    return <div>{children}</div>;
  },
  Page: ({
    pageNumber,
    scale,
    onLoadError,
    onRenderError,
  }: {
    pageNumber: number;
    scale?: number;
    onLoadError?: (error: Error) => void;
    onRenderError?: (error: Error) => void;
  }) => {
    useEffect(() => {
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
  return <FilePreviewBody preview={preview} fileName={name} actions />;
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

/** A file that cannot render shows one card, with the only download. */
function expectUnavailableCard(fileName: string) {
  expect(screen.getByText("Cannot preview this file")).toBeVisible();
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
    await act(async () =>
      respond(fileResponse("hello", "text/plain", "notes.txt"))
    );
    expect(await screen.findByText("hello")).toBeVisible();
    expect(screen.queryByRole("status", { name: "Loading" })).toBeNull();
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
  test("code shows highlighted source, its line count, copy and download", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse('<h1 class="x">Report</h1>\n', "text/html", "page.html")
      );
    const view = renderPreview("page.html");

    // HTML shows as source, never as a rendered page
    expect(await screen.findByText(/Report/)).toBeVisible();
    expect(view.container.querySelector("pre")).toHaveTextContent(
      '<h1 class="x">Report</h1>'
    );
    expect(view.container.querySelector("h1, iframe")).toBeNull();
    expect(screen.getByText("2 lines")).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy content" })).toBeVisible();
    expectDownloadLink("Download", "page.html");
    await waitFor(() =>
      expect(view.container.querySelector("pre .hljs-tag")).not.toBeNull()
    );
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
      expect(view.container.querySelector("pre")?.textContent).toContain(
        '\n    "k": 0\n'
      )
    );
    // The small file loads the grammars, which the large one must not use
    const small = render(<CodeFilePreview text='{"a":1}' language="json" />);
    await waitFor(() =>
      expect(small.container.querySelector("pre span")).not.toBeNull()
    );
    expect(view.container.querySelector("pre span")).toBeNull();
  });

  test("JSON shows indented", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse('{"a":{"b":1}}', "application/json", "data.json")
      );
    const view = renderPreview("data.json");

    await waitFor(() =>
      expect(view.container.querySelector("pre")?.textContent).toBe(
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
      expect(view.container.querySelector("pre")?.textContent).toMatch(/^# Big/)
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
      true,
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

  const PPTX_TYPE =
    "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  const slideRoot = (region: HTMLElement) =>
    Array.from(region.querySelectorAll("div")).find(
      (element) => element.shadowRoot
    )?.shadowRoot;
  const slideMarkup = (text: string) =>
    `<div class="slide" style="position: relative; width: 960px; height: 540px;"><div>${text}</div></div>`;

  test("a PowerPoint deck shows a loader, then its slides with a slide list and arrows", async () => {
    let respond: (slides: string[]) => void = () => undefined;
    jest.mocked(pptxToHtml).mockReturnValue(
      new Promise((resolve) => {
        respond = resolve;
      })
    );
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("deck", PPTX_TYPE, "deck.pptx"));
    renderPreview("deck.pptx");

    expect(
      await screen.findByRole("status", { name: "Loading" })
    ).toBeVisible();
    await act(async () =>
      respond([slideMarkup("Q3 review"), slideMarkup("Next steps")])
    );

    const toolbar = await screen.findByRole("toolbar", {
      name: "Presentation controls",
    });
    expect(within(toolbar).getByText("Slide 1 of 2")).toBeVisible();
    const shown = () => screen.getByRole("region", { name: /^Slide \d of 2$/ });
    expect(slideRoot(shown())?.textContent).toBe("Q3 review");
    fireEvent.click(screen.getByRole("button", { name: "Next slide" }));
    expect(within(toolbar).getByText("Slide 2 of 2")).toBeVisible();
    expect(slideRoot(shown())?.textContent).toBe("Next steps");
    expect(screen.getByRole("button", { name: "Next slide" })).toBeDisabled();
    // The slide list selects a slide, and the arrow keys move in it. It is
    // one tab stop, the current slide, and focus follows the arrow keys.
    const first = screen.getByRole("button", { name: "Slide 1 of 2" });
    const second = screen.getByRole("button", { name: "Slide 2 of 2" });
    fireEvent.click(first);
    expect(within(toolbar).getByText("Slide 1 of 2")).toBeVisible();
    expect(first).toHaveAttribute("tabindex", "0");
    expect(second).toHaveAttribute("tabindex", "-1");
    act(() => first.focus());
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(within(toolbar).getByText("Slide 2 of 2")).toBeVisible();
    expect(second).toHaveFocus();
    expect(second).toHaveAttribute("tabindex", "0");
    expectDownloadLink("Download", "deck.pptx");
  });

  test("a PowerPoint deck that does not parse offers one download", async () => {
    jest.mocked(pptxToHtml).mockRejectedValue(new Error("corrupt"));
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("broken", PPTX_TYPE, "bad.pptx"));
    renderPreview("bad.pptx");

    await screen.findByText("Cannot preview this file");
    expectUnavailableCard("bad.pptx");
  });

  test("a slide runs no script and loads nothing from outside the deck", async () => {
    const ran = jest.fn();
    Object.assign(window, { mockSlideScriptRan: ran });
    jest
      .mocked(pptxToHtml)
      .mockResolvedValue([
        slideMarkup(
          '<script>window.mockSlideScriptRan()</script><img src="x" onerror="window.mockSlideScriptRan()"><img src="https://tracker.example/p.png"><img src="data:image/png;base64,AAAA"><div style="background-image: url(\'https://tracker.example/bg.png\'); color: red;">Safe text</div>'
        ),
      ]);
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("deck", PPTX_TYPE, "deck.pptx"));
    renderPreview("deck.pptx");

    const region = await screen.findByRole("region", { name: "Slide 1 of 1" });
    const root = slideRoot(region);
    expect(root?.textContent).toContain("Safe text");
    expect(root?.querySelector("script")).toBeNull();
    expect(root?.querySelector("[onerror]")).toBeNull();
    const sources = Array.from(root?.querySelectorAll("img") ?? []).map(
      (image) => image.getAttribute("src")
    );
    expect(sources).toEqual([null, null, "data:image/png;base64,AAAA"]);
    const styled = root?.querySelector<HTMLElement>("[style*='color']");
    expect(styled?.style.backgroundImage).toBe("");
    expect(styled?.style.color).toBe("red");
    expect(ran).not.toHaveBeenCalled();
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

  async function renderDeck() {
    jest.mocked(pptxToHtml).mockResolvedValue([slideMarkup("Q3 review")]);
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(fileResponse("deck", PPTX_TYPE, "deck.pptx"));
    renderPreview("deck.pptx");
    await screen.findByRole("region", { name: "Slide 1 of 1" });
  }

  const separator = () =>
    screen.queryByRole("separator", { name: "Resize slide thumbnails" });

  test("a deck's thumbnail column follows the width of the row that holds it, and keeps its state at width 0", async () => {
    const observed = observeResizes();
    try {
      await renderDeck();
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
        screen.getByRole("button", { name: "Toggle slide thumbnails" })
      );
      expect(separator()).not.toBeInTheDocument();
      // The toggle wins over a later width
      resize(900);
      expect(separator()).not.toBeInTheDocument();
    } finally {
      jest.restoreAllMocks();
    }
  });

  test("a deck on a phone-width preview mounts without its thumbnail column", async () => {
    // The observer never reports: the row's width comes from its mount
    observeResizes();
    jest
      .spyOn(HTMLElement.prototype, "clientWidth", "get")
      .mockReturnValue(390);
    try {
      await renderDeck();
      expect(separator()).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Toggle slide thumbnails" })
      ).toHaveAttribute("aria-pressed", "false");
    } finally {
      jest.restoreAllMocks();
    }
  });

  test("a Word document shows a loader, then its pages in a shadow root", async () => {
    const body = document.createElement("div");
    body.innerHTML = "<section class='docx'><p>Project proposal</p></section>";
    let rendered: (
      value: Awaited<ReturnType<typeof renderDocx>>
    ) => void = () => undefined;
    jest.mocked(renderDocx).mockReturnValue(
      new Promise((resolve) => {
        rendered = resolve;
      })
    );
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "docx",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "proposal.docx"
        )
      );
    const view = renderPreview("proposal.docx");

    await waitFor(() => expect(renderDocx).toHaveBeenCalled());
    expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
    await act(async () =>
      rendered({ body, styles: document.createElement("div") })
    );
    await waitFor(() =>
      expect(
        Array.from(view.container.querySelectorAll("div")).some((element) =>
          element.shadowRoot?.textContent?.includes("Project proposal")
        )
      ).toBe(true)
    );
    expect(screen.getByText("2 words")).toBeVisible();
    expect(screen.getByRole("button", { name: "Copy content" })).toBeVisible();
    expectDownloadLink("Download", "proposal.docx");
  });

  test("a Word document that renders in a hidden tab counts and copies its words", async () => {
    const writeText = jest.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const body = document.createElement("div");
    body.innerHTML =
      "<section class='docx'><p>Quarterly plan</p><table><tr><td><p>Revenue up</p></td></tr></table></section>";
    // A hidden subtree has no laid-out text
    Object.defineProperty(body, "innerText", { value: "" });
    jest
      .mocked(renderDocx)
      .mockResolvedValue({ body, styles: document.createElement("div") });
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "docx",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "plan.docx"
        )
      );
    render(
      <div style={{ visibility: "hidden" }}>
        <FilePreviewScope>
          <PreviewOf name="plan.docx" />
        </FilePreviewScope>
      </div>
    );

    expect(await screen.findByText("4 words")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Copy content"));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("Quarterly plan\nRevenue up")
    );
  });

  test("a Word document's manual line break separates words", async () => {
    const writeText = jest.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const body = document.createElement("div");
    body.innerHTML = "<section class='docx'><p>First<br>Second</p></section>";
    jest
      .mocked(renderDocx)
      .mockResolvedValue({ body, styles: document.createElement("div") });
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "docx",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "lines.docx"
        )
      );
    renderPreview("lines.docx");

    expect(await screen.findByText("2 words")).toBeVisible();
    fireEvent.click(screen.getByLabelText("Copy content"));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("First\nSecond")
    );
  });

  test("a Word document that does not render offers one download", async () => {
    jest.mocked(renderDocx).mockRejectedValue(new Error("corrupt"));
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "docx",
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "bad.docx"
        )
      );
    renderPreview("bad.docx");

    await screen.findByText("Cannot preview this file");
    expectUnavailableCard("bad.docx");
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
