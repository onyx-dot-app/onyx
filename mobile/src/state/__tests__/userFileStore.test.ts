import { beforeEach, describe, expect, it, jest } from "@jest/globals";

import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
import {
  setUploadCancel,
  useUserFileStore,
  type FileRecord,
  type UploadTarget,
} from "@/state/userFileStore";

const DRAFT: UploadTarget = { kind: "draft", draftKey: "chat-1:" };

function file(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return {
    id: "tmp-1",
    temp_id: "tmp-1",
    name: "a.pdf",
    file_id: "tmp-1",
    status: UserFileStatus.UPLOADING,
    chat_file_type: ChatFileType.DOCUMENT,
    token_count: null,
    created_at: "",
    ...overrides,
  };
}

function record(clientId = "tmp-1"): FileRecord {
  return {
    clientId,
    file: file({ id: clientId, temp_id: clientId, file_id: clientId }),
  };
}

function reset() {
  useUserFileStore.setState({
    filesById: {},
    serverIdToClientId: {},
    tasksById: {},
    progressById: {},
    epochCounter: 0,
  });
}

describe("userFileStore", () => {
  beforeEach(reset);

  it("beginUpload inserts optimistic records + tasks and stamps the task epoch", () => {
    const epoch = useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    const state = useUserFileStore.getState();
    expect(state.filesById["tmp-1"]!.file.status).toBe(
      UserFileStatus.UPLOADING,
    );
    expect(state.tasksById["tmp-1"]!.epoch).toBe(epoch);
  });

  it("reconcile swaps temp→server (record key stays), server wins, task goes terminal", () => {
    const epoch = useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    useUserFileStore.getState().reconcile(
      [
        file({
          id: "srv-1",
          file_id: "blob-1",
          temp_id: "tmp-1",
          status: UserFileStatus.COMPLETED,
        }),
      ],
      epoch,
    );
    const state = useUserFileStore.getState();
    expect(state.filesById["tmp-1"]!.file.id).toBe("srv-1");
    expect(state.filesById["tmp-1"]!.file.status).toBe(
      UserFileStatus.COMPLETED,
    );
    expect(state.tasksById["tmp-1"]!.status).toBe("succeeded");
    // The identity index now resolves the server id back to the temp clientId.
    expect(state.serverIdToClientId["srv-1"]).toBe("tmp-1");
  });

  it("the epoch guard drops a superseded reconcile", () => {
    const epoch = useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    useUserFileStore
      .getState()
      .reconcile(
        [file({ temp_id: "tmp-1", status: UserFileStatus.COMPLETED })],
        epoch + 99,
      );
    expect(useUserFileStore.getState().filesById["tmp-1"]!.file.status).toBe(
      UserFileStatus.UPLOADING,
    );
  });

  it("setProgress (to progressById) is epoch-guarded", () => {
    const epoch = useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    useUserFileStore.getState().setProgress("tmp-1", epoch, 0.5);
    expect(useUserFileStore.getState().progressById["tmp-1"]).toBe(0.5);
    useUserFileStore.getState().setProgress("tmp-1", epoch + 1, 0.9);
    expect(useUserFileStore.getState().progressById["tmp-1"]).toBe(0.5);
  });

  it("a later poll reconcile (no epoch) matches by server id and patches status", () => {
    const epoch = useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    useUserFileStore.getState().reconcile(
      [
        file({
          id: "srv-1",
          temp_id: "tmp-1",
          status: UserFileStatus.INDEXING,
        }),
      ],
      epoch,
    );
    useUserFileStore
      .getState()
      .reconcile([file({ id: "srv-1", status: UserFileStatus.COMPLETED })]);
    expect(useUserFileStore.getState().filesById["tmp-1"]!.file.status).toBe(
      UserFileStatus.COMPLETED,
    );
  });

  it("removeFile drops the record + task", () => {
    useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    useUserFileStore.getState().removeFile("tmp-1", DRAFT);
    const state = useUserFileStore.getState();
    expect(state.filesById["tmp-1"]).toBeUndefined();
    expect(state.tasksById["tmp-1"]).toBeUndefined();
  });

  it("removeFile from a non-owning target neither cancels nor deletes the owner's upload", () => {
    const draftB: UploadTarget = { kind: "draft", draftKey: "chat-2:" };
    useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    const cancel = jest.fn();
    setUploadCancel("tmp-1", cancel);

    // non-owner (recent-attached elsewhere) removes it → no-op
    useUserFileStore.getState().removeFile("tmp-1", draftB);
    expect(cancel).not.toHaveBeenCalled();
    expect(useUserFileStore.getState().filesById["tmp-1"]).toBeDefined();
    expect(useUserFileStore.getState().tasksById["tmp-1"]).toBeDefined();

    // owner removes it → cancels + drops
    useUserFileStore.getState().removeFile("tmp-1", DRAFT);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(useUserFileStore.getState().filesById["tmp-1"]).toBeUndefined();
    expect(useUserFileStore.getState().tasksById["tmp-1"]).toBeUndefined();
  });

  it("registerExisting adds a recent file with no task (idempotent)", () => {
    const id = useUserFileStore
      .getState()
      .registerExisting(file({ id: "r1", status: UserFileStatus.COMPLETED }));
    expect(id).toBe("r1");
    useUserFileStore.getState().registerExisting(file({ id: "r1" }));
    expect(Object.keys(useUserFileStore.getState().filesById)).toEqual(["r1"]);
    expect(useUserFileStore.getState().tasksById["r1"]).toBeUndefined();
  });

  it("registerExisting references an already-resident file, never duplicating it", () => {
    // Upload a file (record keyed by temp id), reconciled to server id "srv-1".
    const epoch = useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    useUserFileStore.getState().reconcile(
      [
        file({
          id: "srv-1",
          temp_id: "tmp-1",
          status: UserFileStatus.INDEXING,
        }),
      ],
      epoch,
    );
    // Attaching the SAME file from the recent picker must reuse the temp-keyed record.
    const clientId = useUserFileStore
      .getState()
      .registerExisting(file({ id: "srv-1", status: UserFileStatus.INDEXING }));
    const state = useUserFileStore.getState();
    expect(clientId).toBe("tmp-1");
    expect(state.filesById["srv-1"]).toBeUndefined();
    expect(state.serverIdToClientId["srv-1"]).toBe("tmp-1");
  });

  it("upsert seeds records with the identity index and no task", () => {
    useUserFileStore
      .getState()
      .upsert([
        file({ id: "r1", status: UserFileStatus.COMPLETED }),
        file({ id: "r2", status: UserFileStatus.INDEXING }),
      ]);
    const state = useUserFileStore.getState();
    expect(state.filesById["r1"]!.file.status).toBe(UserFileStatus.COMPLETED);
    expect(state.serverIdToClientId["r1"]).toBe("r1");
    expect(state.tasksById["r1"]).toBeUndefined();
  });

  it("upsert reuses a reconciled upload's record by server id (no duplicate) and clears its task", () => {
    const epoch = useUserFileStore
      .getState()
      .beginUpload({ kind: "project", projectId: 5 }, [record()]);
    useUserFileStore.getState().reconcile(
      [
        file({
          id: "srv-1",
          temp_id: "tmp-1",
          status: UserFileStatus.INDEXING,
        }),
      ],
      epoch,
    );
    // Project-details returns the same file keyed by its server id; upsert scopes the task clear.
    useUserFileStore
      .getState()
      .upsert([file({ id: "srv-1", status: UserFileStatus.INDEXING })], {
        kind: "project",
        projectId: 5,
      });
    const state = useUserFileStore.getState();
    // The record stays keyed by the temp clientId; no separate "srv-1" record is created.
    expect(state.serverIdToClientId["srv-1"]).toBe("tmp-1");
    expect(state.filesById["srv-1"]).toBeUndefined();
    expect(Object.keys(state.filesById)).toEqual(["tmp-1"]);
    // The succeeded task is cleared once committed (no phantom optimistic row on unlink).
    expect(state.tasksById["tmp-1"]).toBeUndefined();
  });

  it("upsert without a target leaves in-flight tasks alone (no cross-surface clear)", () => {
    const epoch = useUserFileStore
      .getState()
      .beginUpload({ kind: "project", projectId: 5 }, [record()]);
    useUserFileStore.getState().reconcile(
      [
        file({
          id: "srv-1",
          temp_id: "tmp-1",
          status: UserFileStatus.INDEXING,
        }),
      ],
      epoch,
    );
    // A recent refetch (no target) upserting the same file must NOT clear the project task.
    useUserFileStore
      .getState()
      .upsert([file({ id: "srv-1", status: UserFileStatus.INDEXING })]);
    expect(useUserFileStore.getState().tasksById["tmp-1"]!.status).toBe(
      "succeeded",
    );
  });

  it("removeFile also drops the identity index entry", () => {
    useUserFileStore
      .getState()
      .registerExisting(file({ id: "r1", status: UserFileStatus.COMPLETED }));
    expect(useUserFileStore.getState().serverIdToClientId["r1"]).toBe("r1");
    useUserFileStore.getState().removeFile("r1", DRAFT);
    expect(
      useUserFileStore.getState().serverIdToClientId["r1"],
    ).toBeUndefined();
  });

  it("reset wipes all state (identity change)", () => {
    useUserFileStore.getState().beginUpload(DRAFT, [record()]);
    useUserFileStore.getState().upsert([file({ id: "r1" })]);
    useUserFileStore.getState().reset();
    const state = useUserFileStore.getState();
    expect(state.filesById).toEqual({});
    expect(state.serverIdToClientId).toEqual({});
    expect(state.tasksById).toEqual({});
    expect(state.epochCounter).toBe(0);
  });
});
