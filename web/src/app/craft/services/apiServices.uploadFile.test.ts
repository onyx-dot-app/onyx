import { uploadFile } from "./apiServices";

const originalFetch = global.fetch;

describe("Craft file uploads", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
    global.fetch = originalFetch;
  });

  it("aborts a stranded upload instead of leaving the attachment loading", async () => {
    global.fetch = jest.fn((_input, init) => {
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true }
        );
      });
    });

    const upload = uploadFile(
      "session-id",
      new File(["image"], "reference.png", { type: "image/png" })
    );
    const rejection = expect(upload).rejects.toThrow(
      "Upload timed out. Remove the file and try again."
    );

    await jest.advanceTimersByTimeAsync(60_000);
    await rejection;
  });
});
