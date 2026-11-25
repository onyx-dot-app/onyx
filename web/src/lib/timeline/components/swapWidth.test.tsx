import { fireEvent, render, waitFor } from "@tests/setup/test-utils";
import { Presence } from "@opal/components";

// jsdom has no layout: the content is 99.25px wide, or 40px when its CSS caps
// it at the box's previous width.
// offsetWidth rounds to whole pixels, as in a browser.
function mockWidths() {
  const width = (el: HTMLElement) => {
    if (!el.classList.contains("opal-presence-swap-content")) return 0;
    return el.style.maxWidth === "none" ? 99.25 : 40;
  };
  jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      return { width: width(this), height: 0 } as DOMRect;
    });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return Math.round(width(this));
    },
  });
}

afterEach(() => {
  jest.restoreAllMocks();
  Reflect.deleteProperty(HTMLElement.prototype, "offsetWidth");
});

test("a swap box measures its content uncapped and rounds up, so a title is not cut", () => {
  mockWidths();
  const { container } = render(
    <Presence.Swap swapKey="a" axis="inline">
      <span>Edited 1 file</span>
    </Presence.Swap>
  );
  const box = container.querySelector<HTMLElement>(".opal-presence-swap");
  const content = container.querySelector<HTMLElement>(
    ".opal-presence-swap-content"
  );
  expect(box?.style.width).toBe("100px");
  expect(content?.style.maxWidth).toBe("");
});

// 10px per character, capped at the box's width unless measured uncapped.
// The test observer never reports, as a capped content box would not.
function mockTitleWidths() {
  jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      const width = (() => {
        if (!this.classList.contains("opal-presence-swap-content")) return 0;
        const full = (this.textContent ?? "").length * 10;
        if (this.style.maxWidth === "none") return full;
        const box = parseFloat(this.parentElement?.style.width ?? "");
        return Number.isNaN(box) ? full : Math.min(full, box);
      })();
      return { width, height: 0 } as DOMRect;
    });
}

function setReducedMotion(reduced: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: reduced && query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

const originalMatchMedia = window.matchMedia;
afterEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: originalMatchMedia,
  });
});

test.each([
  ["reduced motion", true],
  ["full motion", false],
])(
  "with %s, a swap to a longer title widens the box though the observer stays quiet",
  async (_, reduced) => {
    mockTitleWidths();
    setReducedMotion(reduced);
    const view = render(
      <Presence.Swap swapKey="a" axis="inline">
        <span>Working</span>
      </Presence.Swap>
    );
    const box = () =>
      view.container.querySelector<HTMLElement>(".opal-presence-swap");
    expect(box()?.style.width).toBe("70px");

    view.rerender(
      <Presence.Swap swapKey="b" axis="inline">
        <span>Worked for 1m 05s</span>
      </Presence.Swap>
    );
    // With motion, the old title leaves before the box resizes.
    const leaving = view.container.querySelector<HTMLElement>(
      '[data-presence-phase="leaving"]'
    );
    if (leaving) fireEvent.animationEnd(leaving);

    await waitFor(() => expect(box()?.style.width).toBe("170px"));
  }
);
