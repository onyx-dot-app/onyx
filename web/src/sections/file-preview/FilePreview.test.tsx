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

const mockPdfLoad = { fail: false };
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
  Page: ({ pageNumber, scale }: { pageNumber: number; scale?: number }) => (
    <div
      data-testid={scale === undefined ? "thumbnail" : "pdf-page"}
      data-page={pageNumber}
    />
  ),
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
});

describe("loading and failure", () => {
  test("shows a loader until the file loads", async () => {
    let respond: (response: Response) => void = () => undefined;
    jest.mocked(fetchChatFile).mockReturnValue(
      new Promise((resolve) => {
        respond = resolve;
      })
    );
    renderPreview("notes.txt");

    expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
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

  test("markdown highlights its fenced code", async () => {
    jest
      .mocked(fetchChatFile)
      .mockResolvedValue(
        fileResponse(
          "# Setup\n\n```python\ndef run():\n    return 1\n```\n",
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
