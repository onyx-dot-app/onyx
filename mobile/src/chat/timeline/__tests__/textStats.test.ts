import { describe, expect, it } from "@jest/globals";

import {
  countLines,
  formatContentSize,
  utf8ByteLength,
} from "@/chat/timeline/textStats";

describe("utf8ByteLength", () => {
  it("counts ASCII as one byte each", () => {
    expect(utf8ByteLength("hello")).toBe(5);
  });

  it("counts multi-byte code points by their UTF-8 width", () => {
    expect(utf8ByteLength("é")).toBe(2);
    expect(utf8ByteLength("→")).toBe(3);
  });

  it("counts a surrogate pair once, as four bytes", () => {
    // "😀" is two UTF-16 units; naively summing per-unit would give 6.
    expect(utf8ByteLength("😀")).toBe(4);
    expect(utf8ByteLength("a😀b")).toBe(6);
  });

  it("is zero for empty text", () => {
    expect(utf8ByteLength("")).toBe(0);
  });
});

describe("formatContentSize", () => {
  it("reports bytes below 1KB", () => {
    expect(formatContentSize("hello")).toBe("5 Bytes");
  });

  it("switches to KB at the boundary", () => {
    expect(formatContentSize("a".repeat(1023))).toBe("1023 Bytes");
    expect(formatContentSize("a".repeat(1024))).toBe("1.00 KB");
    expect(formatContentSize("a".repeat(2560))).toBe("2.50 KB");
  });
});

describe("countLines", () => {
  it("counts a single line with no newline", () => {
    expect(countLines("one line")).toBe(1);
  });

  it("counts blank lines between paragraphs", () => {
    expect(countLines("# Heading\n\nbody")).toBe(3);
  });

  it("counts a trailing newline as opening another line", () => {
    expect(countLines("a\n")).toBe(2);
  });

  it("counts empty text as one line", () => {
    expect(countLines("")).toBe(1);
  });
});
