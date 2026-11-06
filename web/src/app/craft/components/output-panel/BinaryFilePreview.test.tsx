import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import BinaryFilePreview from "@/app/craft/components/output-panel/BinaryFilePreview";

const originalFetch = global.fetch;
beforeEach(() => {
  global.fetch = jest.fn();
  URL.createObjectURL = jest.fn(() => "blob:preview");
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => {
  global.fetch = originalFetch;
  jest.restoreAllMocks();
});

it("offers a retry after a failed read and then plays the file", async () => {
  // GET /api/build/sessions/retry/artifacts/outputs/music.mp3
  jest
    .mocked(fetch)
    .mockResolvedValueOnce(new Response("", { status: 500 }))
    .mockResolvedValue(
      new Response("audio", { headers: { "Content-Type": "audio/mpeg" } })
    );
  render(
    <BinaryFilePreview
      kind="audio"
      sessionId="retry"
      filePath="outputs/music.mp3"
      revision="1"
    />
  );
  fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
  expect(await screen.findByLabelText("music.mp3")).toHaveAttribute(
    "src",
    "blob:preview"
  );
});

it("offers a download when the browser cannot decode media", async () => {
  jest.mocked(fetch).mockResolvedValue(new Response("video"));
  render(
    <BinaryFilePreview
      kind="video"
      sessionId="codec"
      filePath="outputs/clip.mov"
      revision="1"
    />
  );
  fireEvent.error(await screen.findByLabelText("clip.mov"));
  expect(await screen.findByText("Playback not supported")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Download file" })
  ).toBeInTheDocument();
});

it("defers hidden reads and distinguishes size limits from unsupported types", async () => {
  jest.mocked(fetch).mockResolvedValue(
    new Response("", {
      headers: { "Content-Length": String(21 * 1024 * 1024) },
    })
  );
  const props = {
    kind: "docx" as const,
    sessionId: "size",
    filePath: "outputs/report.docx",
    revision: "1",
  };
  const { rerender } = render(
    <BinaryFilePreview {...props} isActive={false} />
  );
  expect(fetch).not.toHaveBeenCalled();
  rerender(<BinaryFilePreview {...props} isActive />);
  expect(
    await screen.findByText("File too large to preview")
  ).toBeInTheDocument();
  expect(screen.getByText(/Files up to 20 MB/)).toBeInTheDocument();
});

it("clears retained media after access is revoked", async () => {
  jest
    .mocked(fetch)
    .mockResolvedValueOnce(new Response("audio"))
    .mockResolvedValue(new Response("", { status: 403 }));
  const props = {
    kind: "audio" as const,
    sessionId: "revoked",
    filePath: "outputs/music.mp3",
  };
  const { rerender } = render(<BinaryFilePreview {...props} revision="1" />);
  await screen.findByLabelText("music.mp3");
  rerender(<BinaryFilePreview {...props} revision="2" />);
  await screen.findByText("Unable to load preview");
  await waitFor(() =>
    expect(screen.queryByLabelText("music.mp3")).not.toBeInTheDocument()
  );
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
});
