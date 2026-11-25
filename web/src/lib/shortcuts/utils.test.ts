import { adjacentChatId, formatHotkey } from "@/lib/shortcuts/utils";

describe("formatHotkey", () => {
  const keyNames = { ctrl: "Strg", alt: "Alt", shift: "Umschalt" };

  it("uses symbols in the macOS order", () => {
    expect(formatHotkey("mod+shift+o", true, keyNames)).toBe("⇧⌘O");
    expect(formatHotkey("mod+alt+1", true, keyNames)).toBe("⌥⌘1");
    expect(formatHotkey("alt+ArrowUp", true, keyNames)).toBe("⌥↑");
  });

  it("uses translated key names elsewhere", () => {
    expect(formatHotkey("mod+shift+o", false, keyNames)).toBe(
      "Strg+Umschalt+O"
    );
    expect(formatHotkey("mod+/", false, keyNames)).toBe("Strg+/");
    expect(formatHotkey("alt+ArrowDown", false, keyNames)).toBe("Alt+↓");
  });
});

describe("adjacentChatId", () => {
  const ids = ["a", "b", "c"];

  it("steps through the list", () => {
    expect(adjacentChatId(ids, "b", 1)).toBe("c");
    expect(adjacentChatId(ids, "b", -1)).toBe("a");
  });

  it("stops at either end", () => {
    expect(adjacentChatId(ids, "c", 1)).toBeNull();
    expect(adjacentChatId(ids, "a", -1)).toBeNull();
  });

  it("enters the list from a chat outside it", () => {
    expect(adjacentChatId(ids, null, 1)).toBe("a");
    expect(adjacentChatId(ids, "x", -1)).toBe("c");
    expect(adjacentChatId([], null, 1)).toBeNull();
  });
});
