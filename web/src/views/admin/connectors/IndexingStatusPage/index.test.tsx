/** The history panel scrolls into view only where it stacks above the list. */
import { revealHistory } from "@/views/admin/connectors/IndexingStatusPage";

function mockWidth(sideBySide: boolean) {
  window.matchMedia = jest.fn().mockReturnValue({ matches: sideBySide });
}

function panel(): HTMLDivElement {
  const element = document.createElement("div");
  element.scrollIntoView = jest.fn();
  return element;
}

describe("revealHistory", () => {
  it("asks for the lg breakpoint the layout stacks below", () => {
    mockWidth(true);
    revealHistory(panel());
    expect(window.matchMedia).toHaveBeenCalledWith("(min-width: 1232px)");
  });

  it("scrolls the panel into view on a narrow screen", () => {
    mockWidth(false);
    const element = panel();
    revealHistory(element);
    expect(element.scrollIntoView).toHaveBeenCalledWith({
      block: "start",
      behavior: "smooth",
    });
  });

  it("leaves the page alone where the panel sits beside the list", () => {
    mockWidth(true);
    const element = panel();
    revealHistory(element);
    expect(element.scrollIntoView).not.toHaveBeenCalled();
  });

  it("ignores the panel unmounting", () => {
    mockWidth(false);
    expect(() => revealHistory(null)).not.toThrow();
  });
});
