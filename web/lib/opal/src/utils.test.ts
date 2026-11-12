/**
 * @jest-environment jsdom
 */
import { isImeComposing } from "@opal/utils";

function keydown(init: KeyboardEventInit & { keyCode?: number }) {
  const event = new KeyboardEvent("keydown", init);
  if (init.keyCode !== undefined) {
    Object.defineProperty(event, "keyCode", { value: init.keyCode });
  }
  return event;
}

describe("isImeComposing", () => {
  it("is true while an IME composes", () => {
    expect(isImeComposing(keydown({ key: "Enter", isComposing: true }))).toBe(
      true
    );
    expect(isImeComposing(keydown({ key: "a", isComposing: true }))).toBe(true);
  });

  it("is true for Safari's confirming Enter with keyCode 229", () => {
    expect(isImeComposing(keydown({ key: "Enter", keyCode: 229 }))).toBe(true);
  });

  it("ignores keyCode 229 on keys other than Enter", () => {
    expect(isImeComposing(keydown({ key: "Backspace", keyCode: 229 }))).toBe(
      false
    );
  });

  it("is false for a plain Enter", () => {
    expect(isImeComposing(keydown({ key: "Enter", keyCode: 13 }))).toBe(false);
  });
});
