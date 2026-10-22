/** @jest-environment jsdom */
import {
  createTurn,
  uploadFile,
  fetchMessages,
  fetchDirectoryListing,
  fetchFileContent,
  fetchPptxPreview,
  fetchOutputThumbnail,
  fetchOutputInventory,
  restoreSession,
} from "@/app/craft/services/apiServices";

const originalFetch = global.fetch;

beforeEach(() => {
  global.fetch = jest.fn();
});
afterEach(() => {
  jest.restoreAllMocks();
  global.fetch = originalFetch;
});

function jsonResponse(status: number, body: object): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Directory reads and artifact cache behavior.
describe("workspace files", () => {
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
    const slides = {
      slide_count: 1,
      slide_paths: ["slide.jpg"],
      cached: false,
    };
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

  it("preserves source previews when MIME guessing reports a binary type", async () => {
    jest.mocked(fetch).mockResolvedValueOnce(
      new Response("export default function Page() {}", {
        headers: { "Content-Type": "application/octet-stream" },
      })
    );
    await expect(
      fetchFileContent("session", "web/src/app/page.tsx")
    ).resolves.toMatchObject({
      content: "export default function Page() {}",
      isImage: false,
    });
  });

  it.each(["outputs/web/bun.lock", "outputs/custom.data"])(
    "previews UTF-8 text with an unknown file type: %s",
    async (path) => {
      jest.mocked(fetch).mockResolvedValueOnce(
        new Response('{"name":"café"}\n', {
          headers: { "Content-Type": "application/octet-stream" },
        })
      );
      await expect(fetchFileContent("session", path)).resolves.toMatchObject({
        content: '{"name":"café"}\n',
        isImage: false,
      });
    }
  );

  it.each([new Uint8Array([255, 128]), new Uint8Array([65, 0, 66])])(
    "rejects non-text bytes even when their extension is unknown",
    async (bytes) => {
      jest.mocked(fetch).mockResolvedValueOnce(
        new Response(bytes, {
          headers: { "Content-Type": "application/octet-stream" },
        })
      );
      await expect(
        fetchFileContent("session", "outputs/custom.data")
      ).resolves.toMatchObject({ content: "", error: "unsupported_binary" });
    }
  );

  it("does not decode oversized unknown files", async () => {
    jest.mocked(fetch).mockResolvedValueOnce(
      new Response(new Uint8Array(10 * 1024 * 1024 + 1).fill(65), {
        headers: { "Content-Type": "application/octet-stream" },
      })
    );
    await expect(
      fetchFileContent("session", "outputs/huge.data")
    ).resolves.toMatchObject({ error: "unsupported_binary" });
  });

  it("does not decode unsupported binary resources as text", async () => {
    const response = new Response(new Uint8Array([0, 255, 128]), {
      headers: { "Content-Type": "application/octet-stream" },
    });
    const text = jest.spyOn(response, "text");
    jest.mocked(fetch).mockResolvedValueOnce(response);
    await expect(
      fetchFileContent("session", "outputs/archive.zip")
    ).resolves.toMatchObject({ content: "", error: "unsupported_binary" });
    expect(text).not.toHaveBeenCalled();
  });

  it("preserves the denied directory status for access loss handling", async () => {
    jest
      .mocked(fetch)
      .mockResolvedValueOnce(new Response("Forbidden", { status: 403 }));
    await expect(fetchDirectoryListing("session")).rejects.toMatchObject({
      status: 403,
    });
  });
});

// Provider selection and attachment payloads.
const selection = {
  providerId: 13,
  providerName: "OpenAI Compatible Test",
  provider: "openai_compatible",
  modelName: "gpt-5-mini",
};

describe("Craft LLM selection payloads", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue(jsonResponse(200, {}));
  });

  it("fails safely on old backends while sending the exact provider id", async () => {
    await createTurn("session-id", "hello", "request-id", undefined, selection);

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const request = jest.mocked(global.fetch).mock.calls[0]![1];
    expect(JSON.parse(String(request!.body))).toMatchObject({
      provider: "onyx",
      provider_id: 13,
      model: "gpt-5-mini",
    });
  });

  it("includes attached sandbox files in the turn payload", async () => {
    await createTurn(
      "session-id",
      "use this",
      "request-id",
      undefined,
      selection,
      [
        {
          name: "reference.png",
          path: "attachments/reference.png",
          mimeType: "image/png",
        },
      ]
    );

    const request = jest.mocked(global.fetch).mock.calls[0]![1];
    expect(JSON.parse(String(request!.body))).toMatchObject({
      attachments: [
        {
          name: "reference.png",
          path: "attachments/reference.png",
          mime_type: "image/png",
        },
      ],
    });
  });

  it("restores attached sandbox files from message metadata", async () => {
    jest.mocked(global.fetch).mockResolvedValueOnce(
      jsonResponse(200, {
        messages: [
          {
            id: "message-1",
            session_id: "session-id",
            turn_index: 0,
            type: "user",
            message_metadata: {
              type: "user_message",
              content: { type: "text", text: "Use this image" },
              attachments: [
                {
                  name: "reference.png",
                  path: "attachments/reference.png",
                  mime_type: "image/png",
                },
              ],
            },
            created_at: "2026-01-01T00:00:00Z",
          },
        ],
      })
    );

    const messages = await fetchMessages("session-id");

    expect(messages[0]?.attachments).toEqual([
      {
        name: "reference.png",
        path: "attachments/reference.png",
        mimeType: "image/png",
      },
    ]);
  });
});

// Restore retries and API failures.
describe("restoreSession", () => {
  it("returns the session on a 200", async () => {
    const session = { id: "s1" };
    const fetchMock = jest
      .mocked(global.fetch)
      .mockResolvedValue(jsonResponse(200, session));

    await expect(restoreSession("s1", { retryDelayMs: 0 })).resolves.toEqual(
      session
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries on a transient 409 and resolves once the lock frees", async () => {
    const session = { id: "s1" };
    const fetchMock = jest
      .mocked(global.fetch)
      .mockResolvedValueOnce(
        jsonResponse(409, { detail: "Restore already in progress" })
      )
      .mockResolvedValueOnce(
        jsonResponse(409, { detail: "Restore already in progress" })
      )
      .mockResolvedValueOnce(jsonResponse(200, session));

    await expect(restoreSession("s1", { retryDelayMs: 0 })).resolves.toEqual(
      session
    );
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("throws after exhausting retries on persistent 409", async () => {
    const fetchMock = jest
      .mocked(global.fetch)
      .mockResolvedValue(
        jsonResponse(409, { detail: "Restore already in progress" })
      );

    await expect(
      restoreSession("s1", { retryDelayMs: 0, maxRetries: 2 })
    ).rejects.toThrow("Restore already in progress");
    // initial attempt + 2 retries
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not retry on a non-409 error", async () => {
    const fetchMock = jest
      .mocked(global.fetch)
      .mockResolvedValue(jsonResponse(500, { detail: "boom" }));

    await expect(restoreSession("s1", { retryDelayMs: 0 })).rejects.toThrow(
      "boom"
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

// First-page output thumbnails share image decoding with file previews.
describe("output thumbnails", () => {
  it("requests an encoded thumbnail and returns its JPEG data URL", async () => {
    jest.mocked(fetch).mockResolvedValueOnce(
      new Response(new Uint8Array([1, 2, 3]), {
        headers: { "Content-Type": "image/jpeg" },
      })
    );
    jest
      .spyOn(FileReader.prototype, "readAsDataURL")
      .mockImplementation(function (this: FileReader) {
        Object.defineProperty(this, "result", {
          value: "data:image/jpeg;base64,AQID",
        });
        this.dispatchEvent(new ProgressEvent("loadend"));
      });
    await expect(
      fetchOutputThumbnail("session", "outputs/annual report.pdf")
    ).resolves.toBe("data:image/jpeg;base64,AQID");
    expect(fetch).toHaveBeenCalledWith(
      "/api/build/sessions/session/output-thumbnail/outputs/annual%20report.pdf",
      { cache: "no-store" }
    );
  });

  it("preserves access errors without attempting image decoding", async () => {
    jest
      .mocked(fetch)
      .mockResolvedValueOnce(new Response("Forbidden", { status: 403 }));
    await expect(
      fetchOutputThumbnail("session", "outputs/report.pdf")
    ).rejects.toMatchObject({ status: 403 });
  });
});

// Inventory errors retain their HTTP status.
it.each([401, 403, 404])(
  "reports terminal output inventory status (%s)",
  async (status) => {
    jest.mocked(fetch).mockResolvedValue(new Response(null, { status }));
    await expect(fetchOutputInventory("session")).rejects.toMatchObject({
      status,
    });
  }
);

// Attachment mutation error contracts.
describe("attachment mutations", () => {
  it.each([401, 403, 404, 503])(
    "preserves HTTP status %s and backend detail",
    async (status) => {
      jest
        .mocked(fetch)
        .mockImplementation(async () =>
          jsonResponse(status, { detail: "Workspace access denied" })
        );
      await expect(
        uploadFile("session", new File(["body"], "notes.txt"))
      ).rejects.toMatchObject({
        status,
        message: "Workspace access denied",
        info: { detail: "Workspace access denied" },
      });
    }
  );
});
