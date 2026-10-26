import { UserFileStatus } from "@/lib/projects/types";
import { isFileBlockingSend } from "@/lib/projects/utils";
import { projectFile } from "@/lib/projects/__tests__/projectFileFixtures";

describe("isFileBlockingSend", () => {
  test.each([
    [UserFileStatus.UPLOADING, false, true],
    [UserFileStatus.PROCESSING, false, true],
    [UserFileStatus.PROCESSING, true, false],
    [UserFileStatus.INDEXING, true, false],
    [UserFileStatus.COMPLETED, true, false],
    [UserFileStatus.SKIPPED, true, false],
  ])("%s with content_ready=%s blocks: %s", (status, content_ready, blocks) => {
    expect(isFileBlockingSend(projectFile({ status, content_ready }))).toBe(
      blocks
    );
  });
});
