import { getUserInitials } from "@/lib/user";

describe("getUserInitials", () => {
  it("returns first letters of first two name parts", () => {
    expect(getUserInitials("Alice Smith", "alice@example.com")).toBe("AS");
  });

  it("returns first two chars of a single-word name", () => {
    expect(getUserInitials("Alice", "alice@example.com")).toBe("AL");
  });

  it("handles three-word names (uses first two)", () => {
    expect(getUserInitials("Alice B. Smith", "alice@example.com")).toBe("AB");
  });

  it("falls back to email local part with dot separator", () => {
    expect(getUserInitials(null, "alice.smith@example.com")).toBe("AS");
  });

  it("falls back to email local part with underscore separator", () => {
    expect(getUserInitials(null, "alice_smith@example.com")).toBe("AS");
  });

  it("falls back to email local part with hyphen separator", () => {
    expect(getUserInitials(null, "alice-smith@example.com")).toBe("AS");
  });

  it("uses first two chars of email local if no separator", () => {
    expect(getUserInitials(null, "alice@example.com")).toBe("AL");
  });

  it("returns null for empty email local part", () => {
    expect(getUserInitials(null, "@example.com")).toBeNull();
  });

  it("uppercases the result", () => {
    expect(getUserInitials("john doe", "jd@test.com")).toBe("JD");
  });

  it("trims whitespace from name", () => {
    expect(getUserInitials("  Alice Smith  ", "a@test.com")).toBe("AS");
  });

  it("returns null for numeric name parts", () => {
    expect(getUserInitials("Alice 1st", "x@test.com")).toBeNull();
  });

  it("returns null for numeric email", () => {
    expect(getUserInitials(null, "42@domain.com")).toBeNull();
  });

  it("falls back to email when name has non-alpha chars", () => {
    expect(getUserInitials("A1", "alice@example.com")).toBe("AL");
  });
});
