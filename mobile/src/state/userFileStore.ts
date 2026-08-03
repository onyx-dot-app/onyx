/**
 * Source of truth for file DATA + the upload lifecycle (tasks + progress). Each file is one record
 * keyed by a stable clientId — a temp id for a fresh upload, the server id otherwise — that never
 * re-keys, so id references survive the temp→server swap (`serverIdToClientId` maps a server id back
 * to its record). It owns NO membership: "which files are in project 7 / recent" lives with each
 * surface, which holds the ids and reads records from here. A task marks one in-flight upload,
 * cleared once its file lands in the list of the surface that started it.
 */
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";

import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";

// Where an upload belongs. No "recent" variant: you never upload *to* the library — a recent file
// enters the store via registerExisting(), not an upload task.
export type UploadTarget =
  | { kind: "draft"; draftKey: string }
  | { kind: "project"; projectId: number };

function sameTarget(a: UploadTarget, b: UploadTarget): boolean {
  if (a.kind === "draft" && b.kind === "draft")
    return a.draftKey === b.draftKey;
  if (a.kind === "project" && b.kind === "project")
    return a.projectId === b.projectId;
  return false;
}

export type TaskStatus = "uploading" | "succeeded";

export interface FileRecord {
  clientId: string; // stable key; never moves on temp→server swap
  file: ProjectFile; // server fields fill in on reconcile
}

export interface UploadTask {
  taskId: string; // === clientId (one task per upload)
  clientId: string;
  target: UploadTarget;
  epoch: number; // run token; late writes self-invalidate
  status: TaskStatus;
}

interface UserFileState {
  filesById: Record<string, FileRecord>;
  // serverId → clientId. Resolves a server-id reference (a project/recent list) to the live record,
  // even for a just-uploaded file still keyed by its temp clientId. Identity, not membership.
  serverIdToClientId: Record<string, string>;
  tasksById: Record<string, UploadTask>;
  progressById: Record<string, number>; // 0..1 by taskId
  epochCounter: number;

  beginUpload: (target: UploadTarget, records: FileRecord[]) => number;
  setProgress: (taskId: string, epoch: number, progress: number) => void;
  // Match a server file by echoed temp_id (fresh upload) else by server id (poll); server wins.
  reconcile: (serverFiles: ProjectFile[], epoch?: number) => void;
  registerExisting: (file: ProjectFile) => string; // recent file → record, no task
  // Loader write-side: upsert already-server files (data + identity index). With a `target`, clears
  // that target's finished (succeeded) tasks for the upserted files, so a committed upload can't
  // resurrect as a phantom optimistic row.
  upsert: (files: ProjectFile[], clearTasksForTarget?: UploadTarget) => void;
  // `target` = the removing surface. Only the target that owns an in-flight upload may cancel +
  // delete it; a non-owner (recent-attached elsewhere) is a no-op.
  removeFile: (clientId: string, target: UploadTarget) => void;
  reset: () => void; // wipe all state on identity change (logout / account switch)
}

// Cancel handles for in-flight uploads (non-serializable → out of store state).
const cancelHandles = new Map<string, () => void>();
export function setUploadCancel(taskId: string, cancel: () => void): void {
  cancelHandles.set(taskId, cancel);
}

// Fallback resolver when the identity index misses (a record exists but wasn't indexed). The index
// is the fast path; this keeps resolution correct without requiring the index to be perfect.
function findClientIdByServerId(
  filesById: Record<string, FileRecord>,
  serverId: string,
): string | undefined {
  for (const record of Object.values(filesById)) {
    if (record.file.id === serverId) return record.clientId;
  }
  return undefined;
}

// Clear a target's succeeded tasks (+ progress) for the given clientIds — called once the files are
// committed. Scoped to the target so a recent refetch can't clear a project task mid-upload.
function clearedTasks(
  state: UserFileState,
  clientIds: string[],
  target: UploadTarget,
): Partial<UserFileState> {
  let tasksById = state.tasksById;
  let progressById = state.progressById;
  for (const id of clientIds) {
    const task = tasksById[id];
    if (task?.status === "succeeded" && sameTarget(task.target, target)) {
      if (tasksById === state.tasksById) tasksById = { ...state.tasksById };
      if (progressById === state.progressById)
        progressById = { ...state.progressById };
      delete tasksById[id];
      delete progressById[id];
    }
  }
  return tasksById === state.tasksById ? {} : { tasksById, progressById };
}

export const useUserFileStore = create<UserFileState>((set, get) => ({
  filesById: {},
  serverIdToClientId: {},
  tasksById: {},
  progressById: {},
  epochCounter: 0,

  beginUpload: (target, records) => {
    const epoch = get().epochCounter + 1;
    set((state) => {
      const filesById = { ...state.filesById };
      const tasksById = { ...state.tasksById };
      for (const record of records) {
        filesById[record.clientId] = record;
        tasksById[record.clientId] = {
          taskId: record.clientId,
          clientId: record.clientId,
          target,
          epoch,
          status: "uploading",
        };
      }
      return { epochCounter: epoch, filesById, tasksById };
    });
    return epoch;
  },

  setProgress: (taskId, epoch, progress) =>
    set((state) => {
      const task = state.tasksById[taskId];
      if (!task || task.epoch !== epoch) return {};
      return { progressById: { ...state.progressById, [taskId]: progress } };
    }),

  reconcile: (serverFiles, epoch) =>
    set((state) => {
      const filesById = { ...state.filesById };
      const tasksById = { ...state.tasksById };
      const serverIdToClientId = { ...state.serverIdToClientId };
      let changed = false;
      for (const server of serverFiles) {
        // Fresh upload → match the echoed temp_id; a later poll (no temp_id) → the identity index
        // (scan fallback if unindexed).
        const clientId =
          server.temp_id != null && filesById[server.temp_id]
            ? server.temp_id
            : (serverIdToClientId[server.id] ??
              findClientIdByServerId(filesById, server.id));
        if (clientId == null || !filesById[clientId]) continue;
        const record = filesById[clientId];
        const task = tasksById[clientId];
        if (epoch != null && task && task.epoch !== epoch) continue;
        filesById[clientId] = {
          ...record,
          file: { ...record.file, ...server },
        };
        serverIdToClientId[server.id] = clientId;
        changed = true;
        if (
          task &&
          task.status === "uploading" &&
          String(server.status).toUpperCase() !== UserFileStatus.UPLOADING
        ) {
          tasksById[clientId] = { ...task, status: "succeeded" };
          cancelHandles.delete(clientId);
        }
      }
      return changed ? { filesById, tasksById, serverIdToClientId } : {};
    }),

  registerExisting: (file) => {
    // Resolve like upsert (index → scan) so a file already resident under a temp clientId is
    // referenced, not duplicated — a duplicate would clobber the index and freeze the original.
    const state = get();
    const existing =
      state.serverIdToClientId[file.id] ??
      findClientIdByServerId(state.filesById, file.id);
    if (existing != null && state.filesById[existing]) return existing;
    set((s) => ({
      filesById: { ...s.filesById, [file.id]: { clientId: file.id, file } },
      serverIdToClientId: { ...s.serverIdToClientId, [file.id]: file.id },
    }));
    return file.id;
  },

  upsert: (files, clearTasksForTarget) =>
    set((state) => {
      const filesById = { ...state.filesById };
      const serverIdToClientId = { ...state.serverIdToClientId };
      const clientIds: string[] = [];
      for (const server of files) {
        // Reuse the record of a just-reconciled upload (its temp clientId), else key by server id.
        const clientId =
          serverIdToClientId[server.id] ??
          findClientIdByServerId(filesById, server.id) ??
          server.id;
        const prev = filesById[clientId];
        filesById[clientId] = prev
          ? { ...prev, file: { ...prev.file, ...server } }
          : { clientId, file: server };
        serverIdToClientId[server.id] = clientId;
        clientIds.push(clientId);
      }
      return {
        filesById,
        serverIdToClientId,
        ...(clearTasksForTarget
          ? clearedTasks(state, clientIds, clearTasksForTarget)
          : {}),
      };
    }),

  removeFile: (clientId, target) => {
    // Skip if a non-owner is removing (recent-attached the file) — don't touch the owner's upload.
    const task = get().tasksById[clientId];
    if (task && !sameTarget(task.target, target)) return;
    cancelHandles.get(clientId)?.();
    cancelHandles.delete(clientId);
    set((state) => {
      const record = state.filesById[clientId];
      if (!record && !state.tasksById[clientId]) return {};
      const filesById = { ...state.filesById };
      const tasksById = { ...state.tasksById };
      const progressById = { ...state.progressById };
      const serverIdToClientId = { ...state.serverIdToClientId };
      if (record) delete serverIdToClientId[record.file.id];
      delete filesById[clientId];
      delete tasksById[clientId];
      delete progressById[clientId];
      return { filesById, tasksById, progressById, serverIdToClientId };
    });
  },

  reset: () => {
    cancelHandles.forEach((cancel) => cancel());
    cancelHandles.clear();
    set({
      filesById: {},
      serverIdToClientId: {},
      tasksById: {},
      progressById: {},
      epochCounter: 0,
    });
  },
}));

export const EMPTY_IDS: readonly string[] = Object.freeze([]);
export const EMPTY_FILES: readonly ProjectFile[] = Object.freeze([]);

// Hot path — one card re-renders per progress tick.
export const useUploadProgress = (clientId: string): number =>
  useUserFileStore((state) => state.progressById[clientId] ?? 0);

// Resolve records for an ordered list of CLIENT ids (drafts hold clientIds). Missing ids filtered.
export const useFilesByIds = (ids: readonly string[]): ProjectFile[] =>
  useUserFileStore(
    useShallow((state) =>
      ids
        .map((id) => state.filesById[id]?.file)
        .filter((file): file is ProjectFile => file != null),
    ),
  );

// Resolve a list of SERVER files (a project/recent list) to their live store records, falling back
// to the given object until the store is seeded. This is what keeps a committed file's status live.
export const useLiveFiles = (files: readonly ProjectFile[]): ProjectFile[] =>
  useUserFileStore(
    useShallow((state) =>
      files.map((file) => {
        const clientId = state.serverIdToClientId[file.id];
        return (clientId ? state.filesById[clientId]?.file : undefined) ?? file;
      }),
    ),
  );
