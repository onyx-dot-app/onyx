import { render } from "@tests/setup/test-utils";
import { Presence } from "@opal/components";

// jsdom has no layout: the content is 100px wide, or 40px when its CSS caps
// it at the box's previous width.
function mockWidths() {
  jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      const capped = this.style.maxWidth !== "none";
      const width = !this.classList.contains("opal-presence-swap-content")
        ? 0
        : capped
          ? 40
          : 100;
      return { width, height: 0 } as DOMRect;
    });
}

afterEach(() => {
  jest.restoreAllMocks();
});

test("a swap box measures its content uncapped, so a longer title is not cut", () => {
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
