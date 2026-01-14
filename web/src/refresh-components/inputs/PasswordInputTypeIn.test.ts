import { computeMaskedInputChange } from "./PasswordInputTypeIn";

describe("computeMaskedInputChange", () => {
  const MASK = "∗"; // ASTERISK OPERATOR (U+2217)

  test("handles typing at any position", () => {
    // Typing "x" in middle of "abcd" -> "abxcd"
    const result = computeMaskedInputChange(
      MASK.repeat(2) + "x" + MASK.repeat(2),
      "abcd",
      3,
      { start: 2, end: 2 }
    );
    expect(result).toEqual({ newValue: "abxcd", cursorPosition: 3 });
  });

  test("handles deletion", () => {
    // Delete at position 1 of "abcd" -> "acd"
    const result = computeMaskedInputChange(MASK.repeat(3), "abcd", 1, {
      start: 1,
      end: 1,
    });
    expect(result).toEqual({ newValue: "acd", cursorPosition: 1 });
  });

  test("handles selection replacement", () => {
    // Select "bc" in "abcd", type "xyz" -> "axyzd"
    const result = computeMaskedInputChange(MASK + "xyz" + MASK, "abcd", 4, {
      start: 1,
      end: 3,
    });
    expect(result).toEqual({ newValue: "axyzd", cursorPosition: 4 });
  });

  test("handles clearing the field", () => {
    const result = computeMaskedInputChange("", "password", 0, {
      start: 0,
      end: 8,
    });
    expect(result).toEqual({ newValue: "", cursorPosition: 0 });
  });

  test("preserves mask character in user input", () => {
    // Pasting "∗∗" to replace "bc" in "abcd" -> "a∗∗d"
    const result = computeMaskedInputChange(
      MASK.repeat(4), // display shows 4 masks
      "abcd",
      3,
      { start: 1, end: 3 }
    );
    expect(result).toEqual({ newValue: "a∗∗d", cursorPosition: 3 });
  });
});
