import { act, render, screen } from "@tests/setup/test-utils";
import { skipRetryOnAuthError } from "@/lib/fetcher";
import PdfPreview from "@/app/craft/components/output-panel/PdfPreview";

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

beforeEach(() => {
  URL.createObjectURL = jest.fn().mockReturnValue("blob:preview");
  URL.revokeObjectURL = jest.fn();
});

afterEach(() => {
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
