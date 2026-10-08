import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

const mockDestroy = jest.fn().mockResolvedValue(undefined);
const mockGetDocument = jest.fn();
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
  getDocument: (...args: unknown[]) => mockGetDocument(...args),
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

beforeEach(() => {
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
afterEach(() => jest.restoreAllMocks());

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
