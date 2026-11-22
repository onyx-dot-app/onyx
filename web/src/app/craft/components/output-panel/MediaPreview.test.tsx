import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import MediaPreview from "@/app/craft/components/output-panel/MediaPreview";

beforeEach(() => {
  URL.createObjectURL = jest.fn(() => "blob:preview");
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

it("pauses hidden media and releases its URL on eviction", async () => {
  const blob = new Blob(["audio"], { type: "audio/mpeg" });
  const props = {
    blob,
    kind: "audio" as const,
    fileName: "music.mp3",
    onError: jest.fn(),
  };
  const { rerender, unmount } = render(<MediaPreview {...props} isActive />);
  expect(await screen.findByLabelText("music.mp3")).toHaveAttribute("controls");
  rerender(<MediaPreview {...props} isActive={false} />);
  await waitFor(() =>
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled()
  );
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
});

it("reports browser playback errors", async () => {
  const onError = jest.fn();
  render(
    <MediaPreview
      blob={new Blob(["video"])}
      kind="video"
      fileName="clip.mov"
      isActive
      onError={onError}
    />
  );
  fireEvent.error(await screen.findByLabelText("clip.mov"));
  expect(onError).toHaveBeenCalled();
});
