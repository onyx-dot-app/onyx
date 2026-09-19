import type { KeyboardEvent } from "react";
import { handleInputNavKeys } from "@/sections/input/inputBarKeys";

const event = {} as KeyboardEvent<HTMLDivElement>;

describe("handleInputNavKeys", () => {
  it("lets queue navigation consume the event first, skipping tile handling", () => {
    const queueNav = { handleKeyDown: jest.fn(() => true) };
    const tile = jest.fn(() => false);
    expect(handleInputNavKeys(event, queueNav, tile)).toBe(true);
    expect(queueNav.handleKeyDown).toHaveBeenCalledTimes(1);
    expect(tile).not.toHaveBeenCalled();
  });

  it("falls through to tile handling when queue navigation declines", () => {
    const queueNav = { handleKeyDown: jest.fn(() => false) };
    const tile = jest.fn(() => true);
    expect(handleInputNavKeys(event, queueNav, tile)).toBe(true);
    expect(queueNav.handleKeyDown).toHaveBeenCalledTimes(1);
    expect(tile).toHaveBeenCalledTimes(1);
  });

  it("returns false when neither handler consumes the event", () => {
    expect(
      handleInputNavKeys(event, { handleKeyDown: () => false }, () => false)
    ).toBe(false);
  });
});
