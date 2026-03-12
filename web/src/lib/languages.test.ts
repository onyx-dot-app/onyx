import {
  getCodeLanguage,
  getDataLanguage,
  getLanguageByMime,
  isMarkdownFile,
} from "./languages";

describe("getCodeLanguage", () => {
  it.each([
    ["app.py", "python"],
    ["index.ts", "typescript"],
    ["main.go", "go"],
    ["style.css", "css"],
    ["page.html", "html"],
    ["App.vue", "vue"],
    ["lib.rs", "rust"],
    ["main.cpp", "c++"],
    ["util.c", "c"],
    ["script.js", "javascript"],
  ])("%s → %s", (filename, expected) => {
    expect(getCodeLanguage(filename)).toBe(expected);
  });

  it.each([
    [".h", "c"],
    [".inc", "php"],
    [".m", "objective-c"],
    [".re", "reason"],
  ])("override: %s → %s", (ext, expected) => {
    expect(getCodeLanguage(`file${ext}`)).toBe(expected);
  });

  it("resolves by exact filename when there is no extension", () => {
    expect(getCodeLanguage("Dockerfile")).toBe("dockerfile");
    expect(getCodeLanguage("Makefile")).toBe("makefile");
  });

  it("is case-insensitive for filenames", () => {
    expect(getCodeLanguage("INDEX.JS")).toBe("javascript");
    expect(getCodeLanguage("dockerfile")).toBe("dockerfile");
  });

  it("returns null for unknown extensions", () => {
    expect(getCodeLanguage("file.xyz123")).toBeNull();
  });

  it("excludes markdown extensions", () => {
    expect(getCodeLanguage("README.md")).toBeNull();
    expect(getCodeLanguage("notes.markdown")).toBeNull();
  });
});

describe("getDataLanguage", () => {
  it.each([
    ["config.json", "json"],
    ["config.yaml", "yaml"],
    ["config.yml", "yaml"],
    ["config.toml", "toml"],
    ["data.xml", "xml"],
    ["data.csv", "csv"],
  ])("%s → %s", (filename, expected) => {
    expect(getDataLanguage(filename)).toBe(expected);
  });

  it("returns null for code files", () => {
    expect(getDataLanguage("app.py")).toBeNull();
  });
});

describe("isMarkdownFile", () => {
  it("recognises markdown extensions", () => {
    expect(isMarkdownFile("README.md")).toBe(true);
    expect(isMarkdownFile("doc.markdown")).toBe(true);
  });

  it("is case-insensitive", () => {
    expect(isMarkdownFile("NOTES.MD")).toBe(true);
  });

  it("rejects non-markdown files", () => {
    expect(isMarkdownFile("app.py")).toBe(false);
    expect(isMarkdownFile("data.json")).toBe(false);
  });
});

describe("getLanguageByMime", () => {
  it("resolves known MIME types", () => {
    expect(getLanguageByMime("text/x-python")).toBe("python");
    expect(getLanguageByMime("text/javascript")).toBe("javascript");
  });

  it("strips parameters before matching", () => {
    expect(getLanguageByMime("text/x-python; charset=utf-8")).toBe("python");
  });

  it("returns null for unknown MIME types", () => {
    expect(getLanguageByMime("application/x-unknown-thing")).toBeNull();
  });
});
