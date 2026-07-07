import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";

import { File } from "expo-file-system";
import { getToken } from "@/api/auth/tokenStore";
import {
  buildFileKey,
  uploadProjectFile,
  type NormalizedAsset,
} from "@/api/files/upload";

// `jest.mock` is hoisted above the imports by babel-jest.
jest.mock("expo-file-system", () => ({
  UploadType: { BINARY_CONTENT: 0, MULTIPART: 1 },
  File: jest.fn(),
}));
jest.mock("@/api/auth/tokenStore", () => ({ getToken: jest.fn() }));
jest.mock("@/api/config", () => ({ getBaseUrl: () => "https://x.test/api" }));

const FileMock = File as unknown as Mock<(uri: string) => unknown>;
const getTokenMock = getToken as unknown as Mock<() => Promise<string | null>>;

interface UploadResultLike {
  status: number;
  body: string;
  headers: Record<string, string>;
}

// Wires `new File(uri).upload(url, options)` and returns the captured upload mock.
function mockUpload(
  result: UploadResultLike,
): Mock<(...args: unknown[]) => unknown> {
  const upload = jest.fn(async () => result) as unknown as Mock<
    (...args: unknown[]) => unknown
  >;
  FileMock.mockImplementation(() => ({ upload }));
  return upload;
}

const asset: NormalizedAsset = {
  uri: "file:///tmp/a.pdf",
  name: "a.pdf",
  mimeType: "application/pdf",
  size: 10,
};

describe("buildFileKey", () => {
  it("matches the backend `${size}|${name[:50]}`", () => {
    expect(buildFileKey(asset)).toBe("10|a.pdf");
  });

  it("truncates the name to 50 chars", () => {
    const long = `${"z".repeat(60)}.pdf`;
    expect(buildFileKey({ uri: "x", name: long, size: 3 })).toBe(
      `3|${long.slice(0, 50)}`,
    );
  });

  it("uses an empty size segment when size is unknown", () => {
    expect(buildFileKey({ uri: "x", name: "a.pdf" })).toBe("|a.pdf");
  });
});

describe("uploadProjectFile", () => {
  beforeEach(() => {
    FileMock.mockReset();
    getTokenMock.mockReset();
  });

  it("sends the web-faithful multipart fields + bearer, and parses the body", async () => {
    getTokenMock.mockResolvedValue("tok");
    const upload = mockUpload({
      status: 200,
      body: JSON.stringify({
        user_files: [{ id: "f1", temp_id: "tmp-1" }],
        rejected_files: [],
      }),
      headers: {},
    });

    const result = await uploadProjectFile(asset, 5, "tmp-1");

    expect(FileMock).toHaveBeenCalledWith("file:///tmp/a.pdf");
    const call = upload.mock.calls[0] as [string, Record<string, unknown>];
    expect(call[0]).toBe("https://x.test/api/user/projects/file/upload");
    const options = call[1] as {
      fieldName: string;
      uploadType: number;
      parameters: Record<string, string>;
      headers: Record<string, string>;
    };
    expect(options.fieldName).toBe("files");
    expect(options.uploadType).toBe(1);
    expect(options.parameters.project_id).toBe("5");
    expect(JSON.parse(options.parameters.temp_id_map)).toEqual({
      "10|a.pdf": "tmp-1",
    });
    expect(options.headers.Authorization).toBe("Bearer tok");
    expect(result.user_files).toHaveLength(1);
  });

  it("omits the Authorization header when there is no token", async () => {
    getTokenMock.mockResolvedValue(null);
    const upload = mockUpload({
      status: 200,
      body: JSON.stringify({ user_files: [], rejected_files: [] }),
      headers: {},
    });

    await uploadProjectFile(asset, 5, "tmp-1");

    const options = (
      upload.mock.calls[0] as [string, { headers?: unknown }]
    )[1];
    expect(options.headers).toBeUndefined();
  });

  it("throws on a non-2xx upload (it resolves, so status is checked)", async () => {
    getTokenMock.mockResolvedValue("tok");
    mockUpload({ status: 500, body: "boom", headers: {} });

    await expect(uploadProjectFile(asset, 5, "tmp-1")).rejects.toThrow();
  });

  it("throws when a 2xx body is valid JSON but the wrong shape", async () => {
    getTokenMock.mockResolvedValue("tok");
    mockUpload({ status: 200, body: JSON.stringify({}), headers: {} });

    await expect(uploadProjectFile(asset, 5, "tmp-1")).rejects.toThrow();
  });

  it("throws an ApiError (not a raw SyntaxError) when a 2xx body isn't JSON", async () => {
    getTokenMock.mockResolvedValue("tok");
    mockUpload({ status: 200, body: "<html>nope</html>", headers: {} });

    await expect(uploadProjectFile(asset, 5, "tmp-1")).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
    });
  });
});
