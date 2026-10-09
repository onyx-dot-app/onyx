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
const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

beforeEach(() => {
  // JSDOM lacks Blob.arrayBuffer(); use Node's binary implementation.
  Object.defineProperty(globalThis, "Blob", {
    configurable: true,
    writable: true,
    value: NodeBlob,
  });
  URL.createObjectURL = jest.fn().mockReturnValue("blob:preview");
  URL.revokeObjectURL = jest.fn();
});

afterEach(() => {
  globalThis.Blob = originalBlob;
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
  jest.restoreAllMocks();
});

it("reuses PDF bytes across tab switches and releases viewer URLs", async () => {
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
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
    await act(async () => {
      await jest.advanceTimersByTimeAsync(11000);
    });
    rerender(preview);
    await screen.findByTitle("report.pdf");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
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

it("keeps an unversioned PDF iframe for identical bytes and replaces changed bytes", async () => {
  const originalBytes = new Uint8Array([37, 80, 68, 70, 0, 255]);
  const changedBytes = new Uint8Array([37, 80, 68, 70, 0, 254]);
  const unchangedResponse = deferred<Response>();
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(originalBytes))
    .mockReturnValueOnce(unchangedResponse.promise)
    .mockResolvedValueOnce(new Response(changedBytes));
  URL.createObjectURL = jest
    .fn()
    .mockReturnValueOnce("blob:original")
    .mockReturnValueOnce("blob:changed");
  const view = (isActive: boolean) => (
    <PdfPreview
      sessionId="unversioned-pdf"
      filePath="web/report.pdf"
      isActive={isActive}
    />
  );
  const { rerender, unmount } = render(view(true));
  const frame = await screen.findByTitle("report.pdf");
  rerender(view(false));
  rerender(view(true));
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(screen.getByTitle("report.pdf")).toBe(frame);
  await act(async () => unchangedResponse.resolve(new Response(originalBytes)));
  expect(screen.getByTitle("report.pdf")).toBe(frame);
  expect(frame).toHaveAttribute("src", "blob:original");
  expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  expect(URL.revokeObjectURL).not.toHaveBeenCalled();

  // Equal byte lengths must not hide an actual edit.
  rerender(view(false));
  rerender(view(true));
  await waitFor(() =>
    expect(screen.getByTitle("report.pdf")).toHaveAttribute(
      "src",
      "blob:changed"
    )
  );
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:original");
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:changed");
});
