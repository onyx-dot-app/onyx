import { beforeEach, describe, expect, it } from "@jest/globals";
import { renderHook } from "@testing-library/react-native";

import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { UserFileStatus } from "@/chat/contracts/projects";
import { useProjectUploads, useUploadStore } from "@/state/uploadStore";

function optimistic(id: string, name = "a.pdf") {
  return makeProjectFile({
    id,
    temp_id: id,
    name,
    file_id: id,
    status: UserFileStatus.UPLOADING,
  });
}

describe("uploadStore", () => {
  beforeEach(() => useUploadStore.setState({ byProject: new Map() }));

  it("adds optimistic uploads under a project and clears prior errors", () => {
    const store = useUploadStore.getState();
    store.setErrors(1, ["old"]);
    store.begin(1, [optimistic("t1"), optimistic("t2")]);

    const bucket = useUploadStore.getState().byProject.get(1);
    expect(bucket?.uploads.size).toBe(2);
    expect(bucket?.errors).toEqual([]);
  });

  it("tracks per-file progress", () => {
    const store = useUploadStore.getState();
    store.begin(1, [optimistic("t1")]);
    store.setProgress(1, "t1", 0.5);

    expect(
      useUploadStore.getState().byProject.get(1)?.uploads.get("t1")?.progress,
    ).toBe(0.5);
  });

  it("removes only the finished optimistic entry", () => {
    const store = useUploadStore.getState();
    store.begin(1, [optimistic("t1"), optimistic("t2")]);
    store.finish(1, "t1");

    const uploads = useUploadStore.getState().byProject.get(1)?.uploads;
    expect(uploads?.has("t1")).toBe(false);
    expect(uploads?.has("t2")).toBe(true);
  });

  it("keeps uploads isolated per project", () => {
    const store = useUploadStore.getState();
    store.begin(1, [optimistic("t1")]);
    store.begin(2, [optimistic("t2")]);

    expect(useUploadStore.getState().byProject.get(1)?.uploads.size).toBe(1);
    expect(useUploadStore.getState().byProject.get(2)?.uploads.size).toBe(1);
  });

  it("setErrors then clearErrors", () => {
    const store = useUploadStore.getState();
    store.setErrors(1, ["too big"]);
    expect(useUploadStore.getState().byProject.get(1)?.errors).toEqual([
      "too big",
    ]);
    store.clearErrors(1);
    expect(useUploadStore.getState().byProject.get(1)?.errors).toEqual([]);
  });

  it("useProjectUploads selects the bucket, or undefined for a null project", () => {
    useUploadStore.getState().begin(3, [optimistic("t1")]);

    const { result: selected } = renderHook(() => useProjectUploads(3));
    expect(selected.current?.uploads.size).toBe(1);

    const { result: none } = renderHook(() => useProjectUploads(null));
    expect(none.current).toBeUndefined();
  });
});
