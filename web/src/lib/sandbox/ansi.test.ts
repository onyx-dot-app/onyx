import { stripAnsi } from "@/lib/sandbox/ansi";

describe("stripAnsi", () => {
  test("removes color codes", () => {
    expect(
      stripAnsi("\u001b[32m3 passed\u001b[0m, \u001b[1;31m1 failed\u001b[m")
    ).toBe("3 passed, 1 failed");
  });

  test("removes cursor moves and OSC links", () => {
    expect(
      stripAnsi(
        "\u001b[2K\u001b[1Gdone \u001b]8;;https://x.dev\u0007link\u001b]8;;\u001b\\"
      )
    ).toBe("done link");
  });

  test("removes a character set selector", () => {
    expect(stripAnsi("\u001b(Bplain")).toBe("plain");
  });

  test("keeps text without escapes", () => {
    expect(stripAnsi("[32m is not an escape")).toBe("[32m is not an escape");
  });
});
