import {
  storedFileList,
  withoutFile,
  withStagedFiles,
} from "@/lib/connectors/edit/files";

describe("file connector edit list", () => {
  const stored = storedFileList(["id-a", "id-b"], ["a.txt", "b.txt"]);

  it("names a stored file by its id when no name is stored", () => {
    expect(storedFileList(["id-a"], null)).toEqual({
      fileIds: ["id-a"],
      fileNames: ["id-a"],
    });
  });

  it("adds staged files and lists a returned current id once", () => {
    expect(
      withStagedFiles(stored, {
        file_paths: ["id-b", "id-c"],
        file_names: ["b.txt", "c.txt"],
      })
    ).toEqual({
      fileIds: ["id-a", "id-b", "id-c"],
      fileNames: ["a.txt", "b.txt", "c.txt"],
    });
  });

  it("removes a file with its name", () => {
    expect(withoutFile(stored, "id-a")).toEqual({
      fileIds: ["id-b"],
      fileNames: ["b.txt"],
    });
  });
});
