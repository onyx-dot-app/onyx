/** @jest-environment jsdom */
import {
  binaryPreviewKind,
  fetchBinaryPreview,
} from "@/app/craft/services/filePreview";

const originalFetch = global.fetch;
beforeEach(() => {
  global.fetch = jest.fn();
});
afterEach(() => {
  global.fetch = originalFetch;
  jest.restoreAllMocks();
});

it("rejects compound extensions and legacy Word files", () => {
  expect(binaryPreviewKind("report.DOCX")).toBe("docx");
  expect(binaryPreviewKind("report.doc")).toBeUndefined();
  expect(binaryPreviewKind("report.xlsx.txt")).toBeUndefined();
});

it("rejects large files before reading their body", async () => {
  // GET /api/build/sessions/session/artifacts/outputs/movie.mp4
  const response = new Response("large", {
    headers: { "Content-Length": "200" },
  });
  const read = jest.spyOn(response, "blob");
  jest.mocked(fetch).mockResolvedValue(response);
  await expect(
    fetchBinaryPreview("session", "outputs/movie.mp4", 100)
  ).resolves.toEqual({ tooLarge: true });
  expect(read).not.toHaveBeenCalled();
});

it("checks size when Content-Length is absent", async () => {
  jest.mocked(fetch).mockResolvedValue(new Response("larger than limit"));
  await expect(
    fetchBinaryPreview("session", "outputs/book.xlsx", 4)
  ).resolves.toEqual({ tooLarge: true });
});

it("preserves access errors so the viewer clears retained bytes", async () => {
  jest.mocked(fetch).mockResolvedValue(new Response("", { status: 403 }));
  await expect(
    fetchBinaryPreview("session", "outputs/book.xlsx", 100)
  ).rejects.toMatchObject({ status: 403 });
});
