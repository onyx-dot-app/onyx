import { nameInitials } from "@/lib/nameInitials";

describe("nameInitials", () => {
  it("takes the first letters of two Latin words", () => {
    expect(nameInitials("Nik Garza", 2)).toBe("NG");
  });

  it("fills from a single Latin word", () => {
    expect(nameInitials("Nik", 2)).toBe("NI");
  });

  it("keeps one letter for agents", () => {
    expect(nameInitials("Research Helper", 1)).toBe("R");
  });

  it("follows the name's script, not the UI locale", () => {
    expect(nameInitials("Mohammed Ali", 2)).toBe("MA");
  });

  it("uses a single grapheme for Arabic names", () => {
    expect(nameInitials("محمد علي", 2)).toBe("م");
  });

  it("uses a single grapheme for Hebrew names", () => {
    expect(nameInitials("משה", 2)).toBe("מ");
  });

  it("uses the first character for Chinese names", () => {
    expect(nameInitials("王小明", 2)).toBe("王");
  });

  it("uses the first syllable for Korean names", () => {
    expect(nameInitials("김철수", 2)).toBe("김");
  });

  it("handles accented Latin letters", () => {
    expect(nameInitials("Élise Dupont", 2)).toBe("ÉD");
    expect(nameInitials("E\u0301lise", 2)).toBe("E\u0301L");
  });

  it("returns null when no letter leads", () => {
    expect(nameInitials("123", 2)).toBeNull();
    expect(nameInitials("  ", 2)).toBeNull();
    expect(nameInitials("\u{1F600} party", 2)).toBeNull();
    expect(nameInitials("A1", 2)).toBeNull();
  });
});
