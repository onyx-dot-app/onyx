import { render } from "@tests/setup/test-utils";
import { Presence } from "@opal/components";

// jsdom has no layout: the content is 100px wide, or 40px when its CSS caps
// it at the box's previous width.
function mockWidths() {
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true,
    get(this: HTMLElement) {
      if (!this.classList.contains("opal-presence-swap-content")) return 0;
      return this.style.maxWidth === "none" ? 100 : 40;
    },
  });
}

afterEach(() => {
  Reflect.deleteProperty(HTMLElement.prototype, "offsetWidth");
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
