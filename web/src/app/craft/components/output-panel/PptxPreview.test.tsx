import { SWRConfig } from "swr";
import { FilePreviewContent } from "@/app/craft/components/output-panel/FilePreviewContent";
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
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchPptxPreview: jest.fn(),
}));

const originalScrollIntoView: typeof Element.prototype.scrollIntoView =
  Element.prototype.scrollIntoView;
beforeEach(() => {
  Element.prototype.scrollIntoView = jest.fn();
});
afterEach(() => {
  Element.prototype.scrollIntoView = originalScrollIntoView;
});

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
  fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
    key: "ArrowRight",
  });
  fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
    key: "ArrowRight",
  });
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
  fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
    key: "ArrowRight",
  });
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

it("navigates from thumbnails and ignores keyboard events while its tab is hidden", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 3,
    slide_paths: ["slide-1.jpg", "slide-2.jpg", "slide-3.jpg"],
    cached: false,
  });
  const { rerender } = render(
    <PptxPreview sessionId="thumbnails" filePath="outputs/deck.pptx" />
  );
  await screen.findByRole("img");
  fireEvent.click(screen.getByRole("button", { name: "Slide 3 of 3" }));
  expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 3 of 3");
  expect(screen.getByRole("button", { name: "Slide 3 of 3" })).toHaveAttribute(
    "aria-current",
    "true"
  );
  expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({
    block: "nearest",
    inline: "nearest",
  });
  fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
    key: "ArrowUp",
  });
  expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 2 of 3");
  rerender(
    <PptxPreview
      sessionId="thumbnails"
      filePath="outputs/deck.pptx"
      isActive={false}
    />
  );
  fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
    key: "ArrowRight",
  });
  expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 2 of 3");
  rerender(<PptxPreview sessionId="thumbnails" filePath="outputs/deck.pptx" />);
  fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
    key: "ArrowRight",
  });
  expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 3 of 3");
});

it.each(["input", "textarea", "select", "contenteditable"])(
  "keeps the selected slide when arrow keys come from a %s",
  async (targetKind: string) => {
    jest.mocked(fetchPptxPreview).mockResolvedValue({
      slide_count: 3,
      slide_paths: ["slide-1.jpg", "slide-2.jpg", "slide-3.jpg"],
      cached: false,
    });
    const { container } = render(
      <PptxPreview sessionId="editing-prompt" filePath="outputs/deck.pptx" />
    );
    await screen.findByRole("img");
    fireEvent.click(screen.getByRole("button", { name: "Slide 2 of 3" }));

    const editor: HTMLElement = document.createElement(
      targetKind === "contenteditable" ? "div" : targetKind
    );
    let eventTarget: HTMLElement = editor;
    if (targetKind === "contenteditable") {
      editor.setAttribute("contenteditable", "true");
      eventTarget = document.createElement("span");
      editor.append(eventTarget);
    }
    container.append(editor);
    eventTarget.focus();

    for (const key of ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"]) {
      expect(fireEvent.keyDown(eventTarget, { key })).toBe(true);
      expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 2 of 3");
    }
  }
);

it("reverses horizontal arrows in RTL and keeps vertical arrows unchanged", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 3,
    slide_paths: ["slide-1.jpg", "slide-2.jpg", "slide-3.jpg"],
    cached: false,
  });
  const originalDirection: string = document.documentElement.dir;
  document.documentElement.dir = "rtl";
  try {
    render(<PptxPreview sessionId="rtl-slides" filePath="outputs/deck.pptx" />);
    await screen.findByRole("img");
    fireEvent.click(screen.getByRole("button", { name: "Slide 2 of 3" }));
    fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
      key: "ArrowLeft",
    });
    expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 3 of 3");
    fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
      key: "ArrowRight",
    });
    expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 2 of 3");
    fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
      key: "ArrowUp",
    });
    expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 1 of 3");
    fireEvent.keyDown(screen.getByRole("toolbar", { name: "Slides" }), {
      key: "ArrowDown",
    });
    expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 2 of 3");
  } finally {
    document.documentElement.dir = originalDirection;
  }
});

it("leaves arrow keys outside the viewer available for scrolling", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 2,
    slide_paths: ["slide-1.jpg", "slide-2.jpg"],
    cached: false,
  });
  render(<PptxPreview sessionId="scoped-keys" filePath="outputs/deck.pptx" />);
  await screen.findByRole("img");
  for (const key of ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"]) {
    expect(fireEvent.keyDown(document.body, { key })).toBe(true);
    expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 1 of 2");
  }
  fireEvent.keyDown(screen.getByRole("button", { name: "Slide 1 of 2" }), {
    key: "ArrowDown",
  });
  expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 2 of 2");
});

it("keeps a hidden deck intact and converts only the latest revision on activation", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 3,
    slide_paths: ["slide-1.jpg", "slide-2.jpg", "slide-3.jpg"],
    cached: false,
  });
  const view = (revision: string, isActive: boolean) => (
    <FilePreviewContent
      sessionId="hidden-conversion"
      filePath="outputs/deck.pptx"
      revision={revision}
      isActive={isActive}
    />
  );
  const { rerender } = render(view("1", true));
  await screen.findByRole("img");
  fireEvent.click(screen.getByRole("button", { name: "Slide 3 of 3" }));
  const image = screen.getByRole("img");
  const url = image.getAttribute("src");
  const requests = jest.mocked(fetchPptxPreview).mock.calls.length;
  rerender(view("2", false));
  rerender(view("3", false));
  expect(screen.getByRole("img")).toBe(image);
  expect(screen.getByRole("img")).toHaveAttribute("src", url);
  expect(fetchPptxPreview).toHaveBeenCalledTimes(requests);
  rerender(view("3", true));
  await waitFor(() =>
    expect(screen.getByRole("img")).not.toHaveAttribute("src", url)
  );
  expect(screen.getByRole("img")).toHaveAttribute("alt", "Slide 3 of 3");
  expect(fetchPptxPreview).toHaveBeenCalledTimes(requests + 1);
});

it("resizes thumbnails with quick pointer release and keyboard limits", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 1,
    slide_paths: ["slide-1.jpg"],
    cached: false,
  });
  render(
    <PptxPreview sessionId="resizable-deck" filePath="outputs/deck.pptx" />
  );
  const divider = await screen.findByRole("separator", {
    name: "Resize slide thumbnails",
  });
  divider.setPointerCapture = jest.fn();
  divider.hasPointerCapture = () => true;
  divider.releasePointerCapture = jest.fn();
  const pointer = (type: string, clientX: number) => {
    const event = new MouseEvent(type, { bubbles: true, button: 0, clientX });
    Object.defineProperty(event, "pointerId", { value: 1 });
    fireEvent(divider, event);
  };
  pointer("pointerdown", 112);
  pointer("pointerup", 180);
  expect(divider).toHaveAttribute("aria-valuenow", "180");
  expect(screen.getByRole("toolbar")).toHaveStyle({ width: "180px" });
  fireEvent.keyDown(divider, { key: "ArrowRight" });
  expect(divider).toHaveAttribute("aria-valuenow", "190");
  fireEvent.keyDown(divider, { key: "End" });
  expect(divider).toHaveAttribute("aria-valuenow", "320");
  fireEvent.keyDown(divider, { key: "Home" });
  expect(divider).toHaveAttribute("aria-valuenow", "88");
  pointer("pointerdown", 88);
  pointer("pointermove", 160);
  pointer("pointercancel", 250);
  expect(divider).toHaveAttribute("aria-valuenow", "160");
});

it("reattaches thumbnail sizing after a failed activation read recovers", async () => {
  const observe = jest.spyOn(ResizeObserver.prototype, "observe");
  const preview = {
    slide_count: 1,
    slide_paths: ["slide-1.jpg"],
    cached: true,
  };
  jest
    .mocked(fetchPptxPreview)
    .mockResolvedValueOnce(preview)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValue(preview);
  const view = (isActive = true) => (
    <SWRConfig value={{ shouldRetryOnError: false }}>
      <PptxPreview
        sessionId="resize-recovery"
        filePath="outputs/deck.pptx"
        isActive={isActive}
      />
    </SWRConfig>
  );
  try {
    const { rerender } = render(view());
    await screen.findByRole("separator");
    const firstCalls = observe.mock.calls.length;
    rerender(view(false));
    rerender(view());
    await screen.findByText("Cannot preview presentation");
    rerender(view(false));
    rerender(view());
    await screen.findByRole("separator");
    expect(observe.mock.calls.length).toBeGreaterThan(firstCalls);
  } finally {
    observe.mockRestore();
  }
});

it("owns loading readiness by slide image URL", async () => {
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 2,
    slide_paths: ["slide-1.jpg", "slide-2.jpg"],
    cached: true,
  });
  render(
    <PptxPreview sessionId="image-readiness" filePath="outputs/deck.pptx" />
  );
  fireEvent.load(await screen.findByRole("img"));
  expect(screen.getByRole("img")).toHaveClass("opacity-100");
  fireEvent.click(screen.getByRole("button", { name: "Slide 2 of 2" }));
  expect(screen.getByRole("img")).toHaveClass("opacity-0");
  fireEvent.load(screen.getByRole("img"));
  expect(screen.getByRole("img")).toHaveClass("opacity-100");
});
