import { ChatFileType } from "@/app/app/interfaces";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { getFileSendBlock } from "@/lib/projects/utils";

function file(overrides: Partial<ProjectFile>): ProjectFile {
  return {
    id: "file",
    name: "file.pdf",
    project_id: null,
    user_id: null,
    file_id: "file-id",
    created_at: "2026-01-01T00:00:00Z",
    status: UserFileStatus.PROCESSING,
    file_type: "application/pdf",
    last_accessed_at: "2026-01-01T00:00:00Z",
    chat_file_type: ChatFileType.DOCUMENT,
    token_count: 1_000,
    chunk_count: null,
    ...overrides,
  };
}

describe("getFileSendBlock", () => {
  test("does not block without files", () => {
    expect(getFileSendBlock([], 10_000)).toBeNull();
  });

  test("blocks while a file is uploading", () => {
    expect(
      getFileSendBlock([file({ status: UserFileStatus.UPLOADING })], 10_000)
    ).toBe("uploading");
  });

  test("does not block a processing file that fits in the context", () => {
    expect(getFileSendBlock([file({ token_count: 5_999 })], 10_000)).toBeNull();
  });

  test("blocks when the files reach 60% of the context", () => {
    expect(getFileSendBlock([file({ token_count: 6_000 })], 10_000)).toBe(
      "tooLarge"
    );
  });

  test("counts indexed files toward the budget while another processes", () => {
    const files = [
      file({
        id: "done",
        status: UserFileStatus.COMPLETED,
        token_count: 4_000,
      }),
      file({ id: "new", token_count: 3_000 }),
    ];
    expect(getFileSendBlock(files, 10_000)).toBe("tooLarge");
  });

  test("does not block large files once they are all indexed", () => {
    expect(
      getFileSendBlock(
        [file({ status: UserFileStatus.COMPLETED, token_count: 50_000 })],
        10_000
      )
    ).toBeNull();
  });

  test("blocks a processing file with no extracted text yet", () => {
    expect(getFileSendBlock([file({ token_count: 0 })], 10_000)).toBe("noText");
    expect(getFileSendBlock([file({ token_count: null })], 10_000)).toBe(
      "noText"
    );
  });

  test("ignores spreadsheets, which are sent as metadata only", () => {
    const spreadsheet = file({
      chat_file_type: ChatFileType.TABULAR,
      token_count: 0,
    });
    expect(getFileSendBlock([spreadsheet], 10_000)).toBeNull();
    expect(
      getFileSendBlock([{ ...spreadsheet, token_count: 50_000 }], 10_000)
    ).toBeNull();
  });
});
