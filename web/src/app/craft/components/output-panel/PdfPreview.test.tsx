import { Blob as NodeBlob } from "node:buffer";
import { skipRetryOnAuthError } from "@/lib/fetcher";
import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

const mockDestroy = jest.fn().mockResolvedValue(undefined);
interface MockPdfDocument {
  numPages: number;
}

interface MockPdfLoadingTask {
  promise: Promise<MockPdfDocument>;
  destroy: () => Promise<void>;
  onPassword?: (submit: (password: string) => void, reason: number) => void;
}

const mockGetDocument = jest.fn<MockPdfLoadingTask, [unknown]>();
const mockSetDocument = jest.fn();
const mockIncreaseScale = jest.fn();
const mockDecreaseScale = jest.fn();
const mockViewer = {
  currentPageNumber: 1,
  currentScaleValue: "",
  setDocument: mockSetDocument,
  increaseScale: mockIncreaseScale,
  decreaseScale: mockDecreaseScale,
};
const mockEvents = new Map<string, (event: object) => void>();

jest.mock("pdfjs-dist", () => ({
  version: "6.4.299",
  GlobalWorkerOptions: {},
  AnnotationMode: { ENABLE: 1 },
  PasswordResponses: { NEED_PASSWORD: 1, INCORRECT_PASSWORD: 2 },
  getDocument: (options: unknown) => mockGetDocument(options),
}));
jest.mock("pdfjs-dist/web/pdf_viewer.mjs", () => ({
  EventBus: jest.fn().mockImplementation(() => ({
    on: (name: string, callback: (event: object) => void) =>
      mockEvents.set(name, callback),
  })),
  PDFLinkService: jest.fn().mockImplementation(() => ({
    setViewer: jest.fn(),
    setDocument: jest.fn(),
  })),
  LinkTarget: { BLANK: 2 },
  PDFViewer: jest.fn().mockImplementation(() => mockViewer),
}));

const originalBlob = globalThis.Blob;

beforeEach(() => {
  // JSDOM lacks Blob.arrayBuffer(); use Node's binary implementation.
  Object.defineProperty(globalThis, "Blob", {
    configurable: true,
    writable: true,
    value: NodeBlob,
  });
  mockEvents.clear();
  mockViewer.currentPageNumber = 1;
  mockViewer.currentScaleValue = "";
  mockGetDocument.mockImplementation(() => ({
    promise: Promise.resolve({ numPages: 2 }),
    destroy: mockDestroy,
  }));
  mockSetDocument.mockImplementation((document: object | null) => {
    if (document) mockEvents.get("pagesinit")?.({});
  });
  const blob = new Blob(["pdf bytes"]);
  Object.defineProperty(blob, "arrayBuffer", {
    value: async () => new Uint8Array([1, 2, 3]).buffer,
  });
  jest
    .spyOn(globalThis, "fetch")
    .mockResolvedValue({ ok: true, blob: async () => blob } as Response);
});
afterEach(() => {
  globalThis.Blob = originalBlob;
  jest.restoreAllMocks();
});

it("reuses PDF bytes across tab switches and releases PDF.js documents", async () => {
  const preview = (
    <PdfPreview
      sessionId="cached-pdf"
      filePath="outputs/report.pdf"
      revision="123:100"
    />
  );
  const { rerender, unmount } = render(preview);
  await screen.findByText("Page 1 of 2");
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  rerender(<div />);
  expect(mockDestroy).toHaveBeenCalledTimes(1);
  expect(mockSetDocument).toHaveBeenCalledWith(null);
  rerender(preview);
  await screen.findByText("Page 1 of 2");
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  expect(mockGetDocument).toHaveBeenCalledTimes(2);
  unmount();
  expect(mockDestroy).toHaveBeenCalledTimes(2);
});

it("fetches edited PDFs and honors explicit reloads", async () => {
  const { rerender } = render(
    <PdfPreview sessionId="edited-pdf" filePath="report.pdf" revision="1" />
  );
  await screen.findByText("Page 1 of 2");
  rerender(
    <PdfPreview sessionId="edited-pdf" filePath="report.pdf" revision="2" />
  );
  await screen.findByText("Page 1 of 2");
  expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  rerender(
    <PdfPreview
      sessionId="edited-pdf"
      filePath="report.pdf"
      revision="2"
      refreshKey={1}
    />
  );
  await screen.findByText("Page 1 of 2");
  expect(globalThis.fetch).toHaveBeenCalledTimes(3);
});

it("navigates pages and controls zoom through PDF.js", async () => {
  const user = setupUser();
  render(<PdfPreview sessionId="controls" filePath="report.pdf" />);
  await screen.findByText("Page 1 of 2");
  expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Next page" }));
  expect(mockViewer.currentPageNumber).toBe(2);
  act(() => mockEvents.get("pagechanging")?.({ pageNumber: 2 }));
  expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Previous page" }));
  expect(mockViewer.currentPageNumber).toBe(1);
  await user.click(screen.getByRole("button", { name: "Zoom in" }));
  expect(mockIncreaseScale).toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Zoom out" }));
  expect(mockDecreaseScale).toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Fit width" }));
  expect(mockViewer.currentScaleValue).toBe("page-width");
});

it("shows a preview error when PDF.js rejects invalid bytes", async () => {
  mockGetDocument.mockImplementation(() => ({
    promise: Promise.reject(new Error("Invalid PDF")),
    destroy: mockDestroy,
  }));
  render(<PdfPreview sessionId="invalid" filePath="broken.pdf" />);
  expect(await screen.findByText("Cannot preview PDF")).toBeInTheDocument();
});

it("destroys a pending document when the viewer unmounts", async () => {
  mockGetDocument.mockImplementation(() => ({
    promise: new Promise(() => {}),
    destroy: mockDestroy,
  }));
  const { unmount } = render(
    <PdfPreview sessionId="pending" filePath="report.pdf" />
  );
  await waitFor(() => expect(mockGetDocument).toHaveBeenCalledTimes(1));
  unmount();
  expect(mockDestroy).toHaveBeenCalledTimes(1);
});

it("releases the worker and observers immediately after a page render fails", async () => {
  const disconnect = jest.spyOn(ResizeObserver.prototype, "disconnect");
  const { unmount } = render(
    <PdfPreview sessionId="render-failure" filePath="report.pdf" />
  );
  await screen.findByText("Page 1 of 2");
  act(() =>
    mockEvents.get("pagerendered")?.({ error: new Error("Render failed") })
  );
  expect(screen.getByText("Cannot preview PDF")).toBeInTheDocument();
  expect(mockDestroy).toHaveBeenCalledTimes(1);
  expect(disconnect).toHaveBeenCalledTimes(1);
  expect(mockSetDocument).toHaveBeenCalledWith(null);
  unmount();
  expect(mockDestroy).toHaveBeenCalledTimes(1);
});

it("opens a protected PDF after an incorrect password and a successful retry", async () => {
  const user = setupUser();
  let resolveDocument: ((document: MockPdfDocument) => void) | undefined;
  const task: MockPdfLoadingTask = {
    promise: new Promise<MockPdfDocument>((resolve) => {
      resolveDocument = resolve;
    }),
    destroy: mockDestroy,
  };
  const submit = jest.fn((password: string) => {
    if (password === "correct") resolveDocument?.({ numPages: 2 });
    else task.onPassword?.(submit, 2);
  });
  mockGetDocument.mockReturnValue(task);
  render(<PdfPreview sessionId="protected" filePath="report.pdf" />);
  await waitFor(() => expect(task.onPassword).toBeDefined());
  act(() => task.onPassword?.(submit, 1));
  expect(screen.getByText("Password required")).toBeInTheDocument();
  await user.type(screen.getByLabelText("PDF password"), "wrong");
  await user.click(screen.getByRole("button", { name: "Open PDF" }));
  expect(submit).toHaveBeenCalledWith("wrong");
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Incorrect password. Try again."
  );
  expect(screen.getByLabelText("PDF password")).toHaveValue("");
  await user.type(screen.getByLabelText("PDF password"), "correct");
  await user.click(screen.getByRole("button", { name: "Open PDF" }));
  await screen.findByText("Page 1 of 2");
  expect(submit).toHaveBeenCalledWith("correct");
  expect(screen.queryByLabelText("PDF password")).not.toBeInTheDocument();
  expect(globalThis.fetch).toHaveBeenCalledTimes(1);
});

it("releases a protected PDF when the password prompt is cancelled", async () => {
  const user = setupUser();
  const task: MockPdfLoadingTask = {
    promise: new Promise<MockPdfDocument>(() => {}),
    destroy: mockDestroy,
  };
  const submit = jest.fn();
  mockGetDocument.mockReturnValue(task);
  const { unmount } = render(
    <PdfPreview sessionId="cancel-password" filePath="report.pdf" />
  );
  await waitFor(() => expect(task.onPassword).toBeDefined());
  act(() => task.onPassword?.(submit, 1));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByText("Cannot preview PDF")).toBeInTheDocument();
  expect(mockDestroy).toHaveBeenCalledTimes(1);
  expect(submit).not.toHaveBeenCalled();
  act(() => task.onPassword?.(submit, 2));
  expect(screen.queryByLabelText("PDF password")).not.toBeInTheDocument();
  unmount();
  expect(mockDestroy).toHaveBeenCalledTimes(1);
});

it("destroys a document when closing an open password prompt", async () => {
  const task: MockPdfLoadingTask = {
    promise: new Promise<MockPdfDocument>(() => {}),
    destroy: mockDestroy,
  };
  mockGetDocument.mockReturnValue(task);
  const { unmount } = render(
    <PdfPreview sessionId="close-password" filePath="report.pdf" />
  );
  await waitFor(() => expect(task.onPassword).toBeDefined());
  act(() => task.onPassword?.(jest.fn(), 1));
  expect(screen.getByLabelText("PDF password")).toBeInTheDocument();
  unmount();
  expect(mockDestroy).toHaveBeenCalledTimes(1);
});

it.each([401, 402, 403])(
  "does not retry a PDF HTTP %s response",
  async (status) => {
    jest.useFakeTimers();
    const fetch: jest.SpyInstance = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("Forbidden", { status }));
    try {
      render(
        <PdfPreview
          sessionId="forbidden-pdf"
          filePath="outputs/report.pdf"
          revision="v1"
        />,
        {
          swrConfig: {
            shouldRetryOnError: true,
            onErrorRetry: skipRetryOnAuthError,
          },
        }
      );
      await act(async () => {});
      expect(screen.getByText("Cannot preview PDF")).toBeInTheDocument();
      await act(async () => jest.advanceTimersByTime(30000));
      expect(fetch).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  }
);

it("retains an unversioned PDF.js document for identical bytes and reloads changed bytes", async () => {
  const originalBytes = new Uint8Array([37, 80, 68, 70, 0, 255]);
  const changedBytes = new Uint8Array([37, 80, 68, 70, 0, 254]);
  const unchangedResponse = deferred<Response>();
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(originalBytes))
    .mockReturnValueOnce(unchangedResponse.promise)
    .mockResolvedValueOnce(new Response(changedBytes));
  const view = (isActive: boolean) => (
    <PdfPreview
      sessionId="unversioned-pdf"
      filePath="web/report.pdf"
      isActive={isActive}
    />
  );
  const { rerender, unmount } = render(view(true));
  await screen.findByText("Page 1 of 2");
  expect(mockGetDocument).toHaveBeenCalledTimes(1);
  rerender(view(false));
  rerender(view(true));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  await act(async () => unchangedResponse.resolve(new Response(originalBytes)));
  expect(mockGetDocument).toHaveBeenCalledTimes(1);
  expect(mockDestroy).not.toHaveBeenCalled();

  // Equal byte lengths must not hide an actual edit.
  rerender(view(false));
  rerender(view(true));
  await waitFor(() => expect(mockGetDocument).toHaveBeenCalledTimes(2));
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(mockDestroy).toHaveBeenCalledTimes(1);
  unmount();
  expect(mockDestroy).toHaveBeenCalledTimes(2);
});
