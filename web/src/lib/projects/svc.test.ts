/**
 * @jest-environment jsdom
 */

import { isUploadCancelled, uploadFiles } from "@/lib/projects/svc";

class FakeXhr extends EventTarget {
  static last: FakeXhr | null = null;
  upload = new EventTarget();
  status = 0;
  responseText = "";
  method = "";
  url = "";
  body: FormData | null = null;
  aborted = false;

  constructor() {
    super();
    FakeXhr.last = this;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  send(body: FormData): void {
    this.body = body;
  }

  abort(): void {
    this.aborted = true;
    this.dispatchEvent(new Event("abort"));
  }

  progress(loaded: number, total: number): void {
    const event = new ProgressEvent("progress", {
      lengthComputable: true,
      loaded,
      total,
    });
    this.upload.dispatchEvent(event);
  }

  respond(status: number, body: unknown): void {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.dispatchEvent(new Event("load"));
  }
}

function lastXhr(): FakeXhr {
  if (!FakeXhr.last) throw new Error("no request was sent");
  return FakeXhr.last;
}

const realXhr = global.XMLHttpRequest;

beforeEach(() => {
  FakeXhr.last = null;
  Object.defineProperty(global, "XMLHttpRequest", {
    value: FakeXhr,
    configurable: true,
    writable: true,
  });
});

afterAll(() => {
  Object.defineProperty(global, "XMLHttpRequest", {
    value: realXhr,
    configurable: true,
    writable: true,
  });
});

const file = new File(["hello"], "notes.txt", { type: "text/plain" });

test("posts the files and reports upload progress", async () => {
  const onProgress = jest.fn();
  const result = uploadFiles([file], 3, ["temp_1"], null, { onProgress });
  const xhr = lastXhr();

  expect(xhr.method).toBe("POST");
  expect(xhr.url).toBe("/api/user/projects/file/upload");
  expect(xhr.body?.getAll("files")).toHaveLength(1);
  expect(xhr.body?.get("project_id")).toBe("3");
  expect(xhr.body?.get("temp_ids")).toBe(JSON.stringify(["temp_1"]));

  xhr.progress(25, 100);
  xhr.progress(100, 100);
  expect(onProgress.mock.calls).toEqual([[0.25], [1]]);

  const uploaded = { user_files: [], rejected_files: [] };
  xhr.respond(200, uploaded);
  await expect(result).resolves.toEqual(uploaded);
});

test("rejects with the status on a failed response", async () => {
  const result = uploadFiles([file]);
  lastXhr().respond(413, { detail: "too large" });
  await expect(result).rejects.toThrow("Upload files failed (Status: 413)");
});

test("an abort signal cancels the request", async () => {
  const controller = new AbortController();
  const result = uploadFiles([file], null, undefined, null, {
    signal: controller.signal,
  });
  controller.abort();

  expect(lastXhr().aborted).toBe(true);
  const error = await result.catch((e: unknown) => e);
  expect(isUploadCancelled(error)).toBe(true);
});
