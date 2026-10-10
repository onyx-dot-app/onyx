import type { ProjectFile } from "@/lib/projects/types";
import { filterOutStagedViewerFiles } from "./agentViewerFileUtils";

const file = (id: string, tempId?: string) =>
  ({ id, temp_id: tempId } as ProjectFile);

describe("filterOutStagedViewerFiles", () => {
  it("removes optimistic files staged by the viewer", () => {
    expect(
      filterOutStagedViewerFiles(
        [file("temp_1"), file("existing")],
        new Set(["temp_1"])
      )
    ).toEqual([file("existing")]);
  });

  it("removes uploads after the server replaces their optimistic IDs", () => {
    expect(
      filterOutStagedViewerFiles(
        [file("server_1", "temp_1"), file("existing")],
        new Set(["temp_1"])
      )
    ).toEqual([file("existing")]);
  });

  it("preserves unrelated chat files and uploads", () => {
    const unrelated = [file("existing"), file("server_2", "temp_2")];
    expect(
      filterOutStagedViewerFiles(unrelated, new Set(["temp_1"]))
    ).toEqual(unrelated);
  });
});
