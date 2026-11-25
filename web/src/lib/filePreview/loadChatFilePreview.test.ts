import { fetchChatFile } from "@/lib/chat/svc";
import { FetchError } from "@/lib/fetcher";
import { loadChatFilePreview } from "@/lib/filePreview/loadChatFilePreview";

jest.mock("@/lib/chat/svc", () => ({
  fetchChatFile: jest.fn(),
}));

const MB = 1024 * 1024;
const signal = new AbortController().signal;

interface TrackedBody {
  stream: ReadableStream<Uint8Array>;
  pulled: () => number;
  cancelled: () => boolean;
}

/** A body that counts the chunks read from it and whether it was cancelled. */
function trackedBody(chunks: Uint8Array[]): TrackedBody {
  let pulls = 0;
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      const chunk = chunks[pulls++];
      if (chunk) controller.enqueue(chunk);
      else controller.close();
    },
    cancel() {
      cancelled = true;
    },
  });
  return { stream, pulled: () => pulls, cancelled: () => cancelled };
}

function fileResponse(
  body: BodyInit | null,
  contentType: string,
  fileName?: string
): Response {
  const headers: Record<string, string> = { "Content-Type": contentType };
  if (fileName)
    headers["Content-Disposition"] = `attachment; filename="${fileName}"`;
  return new Response(body, { headers });
}

const SHEETS = {
  sheets: [
    { name: "Summary", csv: "Region,Revenue\nNorth,1200\n", truncated: false },
  ],
};

test("a text file reads its body; the response names the file and its type", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(
      fileResponse("print(1)\nprint(2)", "text/x-python", "stored.py")
    );

  const data = await loadChatFilePreview("file-1", "shown name", signal);

  expect(fetchChatFile).toHaveBeenCalledWith("file-1", "original", signal);
  expect(data).toEqual({
    name: "stored.py",
    mimeType: "text/x-python",
    kind: "code",
    language: "python",
    text: "print(1)\nprint(2)",
    size: 17,
    lineCount: 2,
  });
});

test("a stored name without an extension gets the one for its type", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(fileResponse("%PDF-1.4", "application/pdf", "report"));

  const data = await loadChatFilePreview("file-1", "report", signal);

  expect(data.name).toBe("report.pdf");
  expect(data.kind).toBe("pdf");
});

test("a spreadsheet name loads only the parsed sheets", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(
      fileResponse(JSON.stringify(SHEETS), "application/json")
    );

  const data = await loadChatFilePreview("file-1", "book.xlsx", signal);

  expect(fetchChatFile).toHaveBeenCalledTimes(1);
  expect(fetchChatFile).toHaveBeenCalledWith("file-1", "parsed", signal);
  expect(data).toMatchObject({ kind: "spreadsheet", sheets: SHEETS.sheets });
});

test("a spreadsheet type drops the workbook and loads the parsed sheets", async () => {
  const workbook = trackedBody([new Uint8Array(10)]);
  jest
    .mocked(fetchChatFile)
    .mockResolvedValueOnce(
      fileResponse(
        workbook.stream,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "renamed"
      )
    )
    .mockResolvedValueOnce(
      fileResponse(JSON.stringify(SHEETS), "application/json")
    );

  const data = await loadChatFilePreview("file-1", "renamed", signal);

  expect(workbook.cancelled()).toBe(true);
  expect(fetchChatFile).toHaveBeenLastCalledWith("file-1", "parsed", signal);
  expect(data).toMatchObject({ kind: "spreadsheet", name: "renamed.xlsx" });
});

const PPTX_TYPE =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";

test("a Word or PowerPoint name loads only the server's PDF", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(
      fileResponse("%PDF-1.4", "application/pdf", "preview.pdf")
    );

  const data = await loadChatFilePreview("file-1", "deck.pptx", signal);

  expect(fetchChatFile).toHaveBeenCalledTimes(1);
  expect(fetchChatFile).toHaveBeenCalledWith("file-1", "pdf", signal);
  if (data.kind !== "pdf") throw new Error(`Expected a PDF, got ${data.kind}`);
  expect(data.name).toBe("deck.pptx");
  expect(data.mimeType).toBe(PPTX_TYPE);
  expect(data.blob.type).toBe("application/pdf");
});

test("a PowerPoint type drops the original and loads the server's PDF", async () => {
  const original = trackedBody([new Uint8Array(10)]);
  jest
    .mocked(fetchChatFile)
    .mockResolvedValueOnce(fileResponse(original.stream, PPTX_TYPE, "renamed"))
    .mockResolvedValueOnce(
      fileResponse("%PDF-1.4", "application/pdf", "preview.pdf")
    );

  const data = await loadChatFilePreview("file-1", "renamed", signal);

  expect(original.cancelled()).toBe(true);
  expect(fetchChatFile).toHaveBeenLastCalledWith("file-1", "pdf", signal);
  expect(data).toMatchObject({ kind: "pdf", name: "renamed.pptx" });
});

test("the server's PDF stops at the PDF limit", async () => {
  const body = trackedBody([new Uint8Array(10)]);
  const response = fileResponse(body.stream, "application/pdf");
  response.headers.set("Content-Length", String(200 * MB));
  jest.mocked(fetchChatFile).mockResolvedValue(response);

  const data = await loadChatFilePreview("file-1", "letter.docx", signal);

  expect(data).toMatchObject({
    kind: "tooLarge",
    limitMB: 100,
    name: "letter.docx",
  });
  expect(body.cancelled()).toBe(true);
});

test("a file the server cannot convert has no preview; other failures fail the load", async () => {
  jest.mocked(fetchChatFile).mockRejectedValueOnce(
    new FetchError("Failed to load document.", 422, {
      error_code: "PREVIEW_UNAVAILABLE",
    })
  );
  await expect(
    loadChatFilePreview("file-1", "deck.pptx", signal)
  ).resolves.toMatchObject({ kind: "unavailable", name: "deck.pptx" });

  jest
    .mocked(fetchChatFile)
    .mockRejectedValueOnce(
      new FetchError("Failed to load document.", 503, null)
    );
  await expect(
    loadChatFilePreview("file-1", "deck.pptx", signal)
  ).rejects.toThrow("Failed to load document.");
});

test("a malformed sheets payload fails the load", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(fileResponse("{}", "application/json"));

  await expect(
    loadChatFilePreview("file-1", "book.xlsx", signal)
  ).rejects.toThrow();
});

test.each([
  ["chart.png", "image/png", "image"],
  ["archive.zip", "application/zip", "unsupported"],
])("%s reads no body", async (name, contentType, kind) => {
  const body = trackedBody([new Uint8Array(10)]);
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(fileResponse(body.stream, contentType, name));

  const data = await loadChatFilePreview("file-1", name, signal);

  expect(data.kind).toBe(kind);
  expect(body.cancelled()).toBe(true);
});

test("a body without a length stops at the format's limit", async () => {
  const chunk = new Uint8Array(MB);
  const body = trackedBody(Array.from({ length: 10 }, () => chunk));
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(fileResponse(body.stream, "text/plain", "huge.log"));

  const data = await loadChatFilePreview("file-1", "huge.log", signal);

  expect(data).toMatchObject({ kind: "tooLarge", limitMB: 5 });
  expect(body.cancelled()).toBe(true);
  expect(body.pulled()).toBeLessThan(10);
});

test("a declared length over the limit reads nothing", async () => {
  const body = trackedBody([new Uint8Array(10)]);
  const response = fileResponse(body.stream, "application/pdf", "big.pdf");
  response.headers.set("Content-Length", String(200 * MB));
  jest.mocked(fetchChatFile).mockResolvedValue(response);

  const data = await loadChatFilePreview("file-1", "big.pdf", signal);

  expect(data).toMatchObject({ kind: "tooLarge", limitMB: 100 });
  expect(body.cancelled()).toBe(true);
});

test("a PDF's bytes stay in their chunks, in one Blob", async () => {
  const body = trackedBody([
    new TextEncoder().encode("%PDF-"),
    new TextEncoder().encode("1.4"),
  ]);
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(fileResponse(body.stream, "application/pdf", "a.pdf"));

  const data = await loadChatFilePreview("file-1", "a.pdf", signal);

  if (data.kind !== "pdf") throw new Error(`Expected a PDF, got ${data.kind}`);
  expect(data.blob.type).toBe("application/pdf");
  expect(await data.blob.text()).toBe("%PDF-1.4");
});

test("a CSV loads as one sheet named for the file", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(fileResponse("a,b\n1,2\n", "text/csv", "sales.csv"));

  const data = await loadChatFilePreview("file-1", "sales.csv", signal);

  expect(data).toMatchObject({
    kind: "csv",
    sheets: [{ name: "sales.csv", csv: "a,b\n1,2\n", truncated: false }],
  });
});
