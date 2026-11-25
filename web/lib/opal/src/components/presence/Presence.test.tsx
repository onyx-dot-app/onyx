import { act, fireEvent, render, screen } from "@tests/setup/test-utils";
import { Presence } from "@opal/components";

// jsdom has no layout. The content's width is its text at 7.3px a
// character, capped (as a title's CSS caps it) at the swap box's set width.
const CHAR_WIDTH = 7.3;

function contentWidth(element: HTMLElement): number {
  const full = (element.textContent ?? "").length * CHAR_WIDTH;
  const box = element.parentElement;
  if (element.style.maxWidth === "none" || !box?.style.width) return full;
  return Math.min(full, parseFloat(box.style.width));
}

function isSwapContent(element: HTMLElement): boolean {
  return element.classList.contains("opal-presence-swap-content");
}

let motion: jest.SpyInstance;
let rect: jest.SpyInstance;
let offsetWidth: jest.SpyInstance;
beforeEach(() => {
  // jsdom's setup reduces motion, which skips the swap's animation.
  motion = jest.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({
        matches: false,
        media: query,
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
      }) as unknown as MediaQueryList
  );
  rect = jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      const width = isSwapContent(this) ? contentWidth(this) : 0;
      return { width, height: 0 } as DOMRect;
    });
  offsetWidth = jest
    .spyOn(HTMLElement.prototype, "offsetWidth", "get")
    .mockImplementation(function (this: HTMLElement) {
      return isSwapContent(this) ? Math.round(contentWidth(this)) : 0;
    });
});
afterEach(() => {
  motion.mockRestore();
  rect.mockRestore();
  offsetWidth.mockRestore();
});

function swapBox(): HTMLElement {
  const box = document.querySelector<HTMLElement>(".opal-presence-swap");
  if (!box) throw new Error("no swap box");
  return box;
}

test("an inline swap widens the box to a longer title, rounded up", () => {
  const view = render(
    <Presence.Swap swapKey="live" axis="inline">
      <p>Working...</p>
    </Presence.Swap>
  );
  expect(swapBox().style.width).toBe(`${Math.ceil(10 * CHAR_WIDTH)}px`);

  view.rerender(
    <Presence.Swap swapKey="done" axis="inline">
      <p>Worked for 12s</p>
    </Presence.Swap>
  );
  const leaving = screen.getByText("Working...").parentElement;
  if (!leaving) throw new Error("no leaving layer");
  act(() => {
    fireEvent.animationEnd(leaving);
  });

  expect(screen.getByText("Worked for 12s")).toBeInTheDocument();
  expect(swapBox().style.width).toBe(`${Math.ceil(14 * CHAR_WIDTH)}px`);
});
