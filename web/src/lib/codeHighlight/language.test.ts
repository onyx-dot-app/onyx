import { loadCodeHighlighter } from "@/lib/codeHighlight/highlighter";
import { getLanguageFromPath } from "@/lib/codeHighlight/language";

test.each(["main.go", "lib.rs", "Foo.java", "x.h", "script.py"])(
  "%s maps to a language the highlighter resolves",
  async (path) => {
    const language = getLanguageFromPath(path);
    expect(language).toBeDefined();
    expect(await loadCodeHighlighter(language ?? "")).not.toBeNull();
  }
);

test("an unknown extension maps to an id the highlighter rejects", async () => {
  const language = getLanguageFromPath("notes.zzzz");
  expect(language).toBe("zzzz");
  expect(await loadCodeHighlighter(language ?? "")).toBeNull();
});

test("no path gives no language", () => {
  expect(getLanguageFromPath(undefined)).toBeUndefined();
});
