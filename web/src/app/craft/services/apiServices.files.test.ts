/** @jest-environment jsdom */
import {
  uploadFile,
  deleteFile,
  fetchDirectoryListing,
  fetchFileContent,
  fetchPptxPreview,
} from "@/app/craft/services/apiServices";

const originalFetch = global.fetch;

beforeEach(() => {
  jest.useFakeTimers();
  global.fetch = jest.fn(
    (_url, options) =>
      new Promise<Response>((_resolve, reject) => {
        options?.signal?.addEventListener("abort", () =>
          reject(options?.signal?.reason)
        );
      })
  );
});

afterEach(() => {
  global.fetch = originalFetch;
  jest.useRealTimers();
});

it("bounds a stalled directory read and allows a later read", async () => {
  const failed = expect(
    fetchDirectoryListing("session", "outputs")
  ).rejects.toMatchObject({ name: "TimeoutError" });
  await jest.advanceTimersByTimeAsync(10_000);
  await failed;
  jest
    .mocked(fetch)
    .mockResolvedValue(
      new Response(JSON.stringify({ path: "outputs", entries: [] }))
    );
  await expect(fetchDirectoryListing("session", "outputs")).resolves.toEqual({
    path: "outputs",
    entries: [],
  });
  expect(jest.getTimerCount()).toBe(0);
});

it("cancels a directory read when its browser becomes inactive", async () => {
  const controller = new AbortController();
  const failed = expect(
    fetchDirectoryListing("session", "outputs", controller.signal)
  ).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  await failed;
  expect(jest.getTimerCount()).toBe(0);
});

it("bypasses HTTP cache for artifact content and presentation conversions", async () => {
  const slides = { slide_count: 1, slide_paths: ["slide.jpg"], cached: false };
  jest
    .mocked(fetch)
    .mockResolvedValueOnce(new Response("updated text"))
    .mockResolvedValueOnce(new Response(JSON.stringify(slides)));

  await expect(
    fetchFileContent("session", "outputs/notes.txt")
  ).resolves.toMatchObject({
    content: "updated text",
  });
  await expect(
    fetchPptxPreview("session", "outputs/slides.pptx")
  ).resolves.toEqual(slides);
  expect(fetch).toHaveBeenNthCalledWith(
    1,
    "/api/build/sessions/session/artifacts/outputs/notes.txt",
    { cache: "no-store" }
  );
  expect(fetch).toHaveBeenNthCalledWith(
    2,
    "/api/build/sessions/session/pptx-preview/outputs/slides.pptx",
    { cache: "no-store" }
  );
});

it("preserves the HTTP status of attachment upload failures", async () => {
  jest
    .mocked(fetch)
    .mockResolvedValue(
      new Response(JSON.stringify({ detail: "Access denied" }), { status: 401 })
    );
  await expect(
    uploadFile("session", new File(["body"], "notes.txt"))
  ).rejects.toMatchObject({ status: 401, message: "Access denied" });
});

it("preserves the HTTP status of attachment deletion failures", async () => {
  jest
    .mocked(fetch)
    .mockResolvedValue(
      new Response(JSON.stringify({ detail: "No such file" }), { status: 404 })
    );
  await expect(
    deleteFile("session", "attachments/notes.txt")
  ).rejects.toMatchObject({ status: 404, message: "No such file" });
});
