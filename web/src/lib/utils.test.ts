import {
  ensureHrefProtocol,
  isBareRelativeHref,
  transformLinkUri,
  getFileIcon,
} from "@/lib/utils";
import {
  SvgSpreadsheetFile,
  SvgAudioFile,
  SvgVideoFile,
  SvgFileText,
} from "@opal/icons";

describe("ensureHrefProtocol", () => {
  it("adds https protocol to bare domains", () => {
    expect(ensureHrefProtocol("anthropic.com")).toBe("https://anthropic.com");
  });

  it("preserves links that already include a protocol", () => {
    expect(ensureHrefProtocol("https://anthropic.com")).toBe(
      "https://anthropic.com"
    );
    expect(ensureHrefProtocol("mailto:support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });

  it("converts bare email addresses to mailto links", () => {
    expect(ensureHrefProtocol("support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });

  it("adds https protocol to a host with a path", () => {
    expect(ensureHrefProtocol("docs.onyx.app/guide")).toBe(
      "https://docs.onyx.app/guide"
    );
  });

  it("keeps a relative path relative", () => {
    expect(ensureHrefProtocol("attachments/artifacts/report.pdf")).toBe(
      "attachments/artifacts/report.pdf"
    );
  });
});

describe("isBareRelativeHref", () => {
  it("is true only for a path with no scheme, host or leading slash", () => {
    expect(isBareRelativeHref("copied_files/tiny.png")).toBe(true);
    expect(isBareRelativeHref("/app/artifacts/abc/v1")).toBe(false);
    expect(isBareRelativeHref("#section")).toBe(false);
    expect(isBareRelativeHref("https://onyx.app")).toBe(false);
    expect(isBareRelativeHref("onyx.app/docs")).toBe(false);
    expect(isBareRelativeHref("support@onyx.app")).toBe(false);
  });
});

describe("transformLinkUri", () => {
  it("allows safe protocols", () => {
    expect(transformLinkUri("https://anthropic.com")).toBe(
      "https://anthropic.com"
    );
    expect(transformLinkUri("mailto:support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });

  it("converts bare email addresses to mailto links", () => {
    expect(transformLinkUri("support@anthropic.com")).toBe(
      "mailto:support@anthropic.com"
    );
  });

  it("blocks unsafe protocols", () => {
    expect(transformLinkUri("javascript:alert(1)")).toBeNull();
  });
});

describe("file category icons", () => {
  it.each([
    "report.xlsx",
    "report.XLS",
    "report.ods",
    "report.csv",
    "report.tsv",
  ])("uses a spreadsheet icon for %s", (name) =>
    expect(getFileIcon(name)).toBe(SvgSpreadsheetFile)
  );
  it.each([
    "recording.mp3",
    "recording.wav",
    "recording.flac",
    "recording.opus",
  ])("uses an audio icon for %s", (name) =>
    expect(getFileIcon(name)).toBe(SvgAudioFile)
  );
  it.each(["clip.mp4", "clip.mov", "clip.mkv", "clip.avi"])(
    "uses a video icon for %s",
    (name) => expect(getFileIcon(name)).toBe(SvgVideoFile)
  );
  it.each(["report.docx", "unknown.bin", "recording.mp3.txt", undefined])(
    "keeps the generic document icon for %s",
    (name) => expect(getFileIcon(name)).toBe(SvgFileText)
  );
});
