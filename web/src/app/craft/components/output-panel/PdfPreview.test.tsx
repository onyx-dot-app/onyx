import { Blob as NodeBlob } from "node:buffer";
import {
  act,
  deferred,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import { skipRetryOnAuthError } from "@/lib/fetcher";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

const originalBlob = globalThis.Blob;
jest.mock("@/app/craft/components/output-panel/PdfDocumentViewer", () => ({
  __esModule: true,
  default: jest.fn(({ blob }: { blob: Blob }) => (
    <div title="report.pdf" data-size={blob.size} />
  )),
}));
import PdfDocumentViewer from "@/app/craft/components/output-panel/PdfDocumentViewer";

beforeEach(() => {
  // JSDOM lacks Blob.arrayBuffer(); use Node's binary implementation.
  Object.defineProperty(globalThis, "Blob", {
    configurable: true,
    writable: true,
    value: NodeBlob,
  });
  jest.mocked(PdfDocumentViewer).mockClear();
});

afterEach(() => {
  globalThis.Blob = originalBlob;
  jest.restoreAllMocks();
});

it("reuses PDF bytes across tab switches", async () => {
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response("pdf bytes"));
  const preview = (
    <PdfPreview
      sessionId="cached-pdf"
      filePath="outputs/report.pdf"
      revision="123:100"
    />
  );
  const { rerender, unmount } = render(preview);
  await screen.findByTitle("report.pdf");
  expect(fetch).toHaveBeenCalledTimes(1);
  jest.useFakeTimers();
  try {
    rerender(<div />);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(11000);
    });
    rerender(preview);
    await screen.findByTitle("report.pdf");
    expect(fetch).toHaveBeenCalledTimes(1);
    unmount();
  } finally {
    jest.useRealTimers();
  }
});

it("fetches edited PDFs and honors explicit reloads", async () => {
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockImplementation(async () => new Response("pdf bytes"));
  const { rerender } = render(
    <PdfPreview
      sessionId="edited-pdf"
      filePath="outputs/report.pdf"
      revision="123:100"
    />
  );
  await screen.findByTitle("report.pdf");
  rerender(
    <PdfPreview
      sessionId="edited-pdf"
      filePath="outputs/report.pdf"
      revision="456:100"
    />
  );
  await screen.findByTitle("report.pdf");
  expect(fetch).toHaveBeenCalledTimes(2);
  rerender(
    <PdfPreview
      sessionId="edited-pdf"
      filePath="outputs/report.pdf"
      revision="456:100"
      refreshKey={1}
    />
  );
  await screen.findByTitle("report.pdf");
  expect(fetch).toHaveBeenCalledTimes(3);
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

it("reuses the displayed Blob for identical bytes and replaces edited bytes", async () => {
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
  const { rerender } = render(view(true));
  await screen.findByTitle("report.pdf");
  const displayed = () =>
    jest.mocked(PdfDocumentViewer).mock.calls.at(-1)?.[0].blob;
  const originalBlob = displayed();
  rerender(view(false));
  rerender(view(true));
  await act(async () => unchangedResponse.resolve(new Response(originalBytes)));
  expect(displayed()).toBe(originalBlob);
  rerender(view(false));
  rerender(view(true));
  await waitFor(() => expect(displayed()).not.toBe(originalBlob));
  expect(fetch).toHaveBeenCalledTimes(3);
});
