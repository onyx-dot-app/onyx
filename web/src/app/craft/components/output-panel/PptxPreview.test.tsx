import {
  render,
  screen,
  waitFor,
  act,
  fireEvent,
} from "@tests/setup/test-utils";
import PptxPreview from "@/app/craft/components/output-panel/PptxPreview";
import {
  fetchPptxPreview,
  type PptxPreviewResponse,
} from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  fetchPptxPreview: jest.fn(),
}));

it("waits for an updated conversion and reloads slide images at the same paths", async () => {
  const converted = {
    slide_count: 1,
    slide_paths: ["outputs/.pptx-preview/deck/slide-1.jpg"],
    cached: false,
  };
  jest.mocked(fetchPptxPreview).mockResolvedValueOnce(converted);
  const { rerender } = render(
    <PptxPreview
      sessionId="preview-revisions"
      filePath="outputs/deck.pptx"
      refreshKey={1}
    />
  );
  const image = await screen.findByRole("img");
  const originalUrl = image.getAttribute("src");
  expect(image).toHaveAttribute("src", expect.stringContaining("revision="));

  let finishConversion: (value: PptxPreviewResponse) => void = () => {};
  jest.mocked(fetchPptxPreview).mockReturnValueOnce(
    new Promise((resolve) => {
      finishConversion = resolve;
    })
  );
  rerender(
    <PptxPreview
      sessionId="preview-revisions"
      filePath="outputs/deck.pptx"
      refreshKey={2}
    />
  );
  await waitFor(() => expect(fetchPptxPreview).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  await act(async () => {
    finishConversion(converted);
  });
  expect(await screen.findByRole("img")).not.toHaveAttribute(
    "src",
    originalUrl
  );
});

it("keeps the selected slide valid when an updated deck has fewer slides", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValueOnce({
    slide_count: 3,
    slide_paths: ["slide-1.jpg", "slide-2.jpg", "slide-3.jpg"],
    cached: false,
  });
  const { rerender } = render(
    <PptxPreview
      sessionId="shrinking-deck"
      filePath="outputs/deck.pptx"
      refreshKey={1}
    />
  );
  await screen.findByRole("img");
  fireEvent.keyDown(window, { key: "ArrowRight" });
  fireEvent.keyDown(window, { key: "ArrowRight" });
  expect(screen.getByRole("img")).toHaveAttribute(
    "src",
    expect.stringContaining("slide-3.jpg")
  );

  jest.mocked(fetchPptxPreview).mockResolvedValueOnce({
    slide_count: 1,
    slide_paths: ["slide-1.jpg"],
    cached: false,
  });
  rerender(
    <PptxPreview
      sessionId="shrinking-deck"
      filePath="outputs/deck.pptx"
      refreshKey={2}
    />
  );
  expect(await screen.findByRole("img")).toHaveAttribute(
    "src",
    expect.stringContaining("slide-1.jpg")
  );
  expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 1 of 1");
});

it("ignores next-slide keys while the deck is converting", async () => {
  let finishConversion: (value: PptxPreviewResponse) => void = () => {};
  jest.mocked(fetchPptxPreview).mockReturnValueOnce(
    new Promise((resolve) => {
      finishConversion = resolve;
    })
  );
  render(<PptxPreview sessionId="loading-deck" filePath="outputs/deck.pptx" />);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  fireEvent.keyDown(window, { key: "ArrowRight" });
  fireEvent.keyDown(window, { key: "ArrowRight" });
  await act(async () => {
    finishConversion({
      slide_count: 2,
      slide_paths: ["slide-1.jpg", "slide-2.jpg"],
      cached: false,
    });
  });
  expect(await screen.findByRole("img")).toHaveAttribute(
    "src",
    expect.stringContaining("slide-1.jpg")
  );
  fireEvent.keyDown(window, { key: "ArrowRight" });
  expect(screen.getByRole("img")).toHaveAttribute(
    "src",
    expect.stringContaining("slide-2.jpg")
  );
});

it("does not reuse old slide URLs when the session refresh counter resets", async () => {
  const converted = {
    slide_count: 1,
    slide_paths: ["outputs/.pptx-preview/deck/slide-1.jpg"],
    cached: false,
  };
  jest.mocked(fetchPptxPreview).mockResolvedValue(converted);
  const preview = (
    <PptxPreview
      sessionId="reopened-session"
      filePath="outputs/deck.pptx"
      refreshKey={1}
    />
  );
  const first = render(preview);
  const originalUrl = (await screen.findByRole("img")).getAttribute("src");
  first.unmount();

  // A fresh browser session can reach the same counter after another edit.
  render(preview);
  const refreshedImage = await screen.findByRole("img");
  expect(refreshedImage).not.toHaveAttribute("src", originalUrl);
});

it("reuses an unchanged preview across tabs after the deduplication window", async () => {
  jest.useFakeTimers();
  try {
    jest.mocked(fetchPptxPreview).mockResolvedValue({
      slide_count: 1,
      slide_paths: ["outputs/.pptx-preview/deck/slide-1.jpg"],
      cached: false,
    });
    const preview = (
      <PptxPreview
        sessionId="cached-deck"
        filePath="outputs/deck.pptx"
        revision="123:100"
      />
    );
    const { rerender } = render(preview);
    const originalUrl = (await screen.findByRole("img")).getAttribute("src");
    const requests = jest.mocked(fetchPptxPreview).mock.calls.length;
    rerender(<div />);
    await act(async () => {
      await jest.advanceTimersByTimeAsync(11000);
    });
    rerender(preview);
    expect(await screen.findByRole("img")).toHaveAttribute("src", originalUrl);
    expect(fetchPptxPreview).toHaveBeenCalledTimes(requests);
  } finally {
    jest.useRealTimers();
  }
});

it("reloads an edited deck by revision and preserves explicit reloads", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 1,
    slide_paths: ["outputs/.pptx-preview/deck/slide-1.jpg"],
    cached: false,
  });
  const { rerender } = render(
    <PptxPreview
      sessionId="edited-deck"
      filePath="outputs/deck.pptx"
      revision="123:100"
    />
  );
  const originalUrl = (await screen.findByRole("img")).getAttribute("src");
  const requests = jest.mocked(fetchPptxPreview).mock.calls.length;
  rerender(
    <PptxPreview
      sessionId="edited-deck"
      filePath="outputs/deck.pptx"
      revision="456:100"
    />
  );
  const updatedUrl = (await screen.findByRole("img")).getAttribute("src");
  expect(updatedUrl).not.toBe(originalUrl);
  expect(fetchPptxPreview).toHaveBeenCalledTimes(requests + 1);
  rerender(
    <PptxPreview
      sessionId="edited-deck"
      filePath="outputs/deck.pptx"
      revision="456:100"
      refreshKey={1}
    />
  );
  expect(await screen.findByRole("img")).not.toHaveAttribute("src", updatedUrl);
  expect(fetchPptxPreview).toHaveBeenCalledTimes(requests + 2);
});
