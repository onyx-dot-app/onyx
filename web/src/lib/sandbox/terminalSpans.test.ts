import { terminalSpans } from "@/lib/sandbox/terminalSpans";

describe("terminalSpans", () => {
  test("a red run is one red span", () => {
    expect(terminalSpans("\u001b[31mfail\u001b[0m")).toEqual([
      { text: "fail", style: { color: "var(--opal-ansi-1)" } },
    ]);
  });

  test("plain text is one unstyled span", () => {
    expect(terminalSpans("ok")).toEqual([{ text: "ok", style: null }]);
  });

  test("256 and truecolor values are inline colors", () => {
    expect(terminalSpans("\u001b[38;5;196mred\u001b[38;2;1;2;3mrgb")).toEqual([
      { text: "red", style: { color: "rgb(255,0,0)" } },
      { text: "rgb", style: { color: "rgb(1,2,3)" } },
    ]);
    expect(terminalSpans("\u001b[38;5;2mgreen")[0]?.style).toEqual({
      color: "var(--opal-ansi-2)",
    });
  });

  test("bold applies until reset", () => {
    expect(terminalSpans("\u001b[1mbold\u001b[0m plain")).toEqual([
      { text: "bold", style: { fontWeight: "600" } },
      { text: " plain", style: null },
    ]);
  });

  test("a cursor escape is dropped", () => {
    expect(terminalSpans("a\u001b[2Kb\u001b]0;title\u0007c")).toEqual([
      { text: "a", style: null },
      { text: "b", style: null },
      { text: "c", style: null },
    ]);
  });
});
