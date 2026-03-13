import { getInitials } from "./utils";

describe("getInitials", () => {
  it("returns first letters of first two name parts", () => {
    expect(getInitials("Alice Smith", "alice@example.com")).toBe("AS");
  });

  it("returns first two chars of a single-word name", () => {
    expect(getInitials("Alice", "alice@example.com")).toBe("AL");
  });

  it("handles three-word names (uses first two)", () => {
    expect(getInitials("Alice B. Smith", "alice@example.com")).toBe("AB");
  });

  it("falls back to email local part with dot separator", () => {
    expect(getInitials(null, "alice.smith@example.com")).toBe("AS");
  });

  it("falls back to email local part with underscore separator", () => {
    expect(getInitials(null, "alice_smith@example.com")).toBe("AS");
  });

  it("falls back to email local part with hyphen separator", () => {
    expect(getInitials(null, "alice-smith@example.com")).toBe("AS");
  });

  it("uses first two chars of email local if no separator", () => {
    expect(getInitials(null, "alice@example.com")).toBe("AL");
  });

  it("returns ? for empty email local part", () => {
    expect(getInitials(null, "@example.com")).toBe("?");
  });

  it("uppercases the result", () => {
    expect(getInitials("john doe", "jd@test.com")).toBe("JD");
  });

  it("trims whitespace from name", () => {
    expect(getInitials("  Alice Smith  ", "a@test.com")).toBe("AS");
  });
});
