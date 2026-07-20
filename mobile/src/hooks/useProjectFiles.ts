import { useCallback, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useShallow } from "zustand/react/shallow";

import { QUERY_KEYS } from "@/api/query-keys";
import { linkFileToProject, unlinkFileFromProject } from "@/api/files/files";
import { pickDocuments, pickImages } from "@/api/files/pickers";
import { getErrorMessage } from "@/api/errors";
import { type NormalizedAsset } from "@/api/files/upload";
import type { ProjectFile } from "@/chat/contracts/projects";
import { toast } from "@/hooks/useToast";
import { useUpload } from "@/hooks/useUpload";
import { useSession } from "@/state/session";
import {
  EMPTY_FILES,
  EMPTY_IDS,
  useFilesByIds,
  useLiveFiles,
  useUserFileStore,
  type UploadTarget,
} from "@/state/userFileStore";

export interface UseProjectFiles {
  // In-flight uploads first, then committed files as live store records.
  files: ProjectFile[];
  addDocuments: () => Promise<void>;
  addImages: () => Promise<void>;
  linkRecent: (fileId: string) => Promise<void>;
  removeFile: (fileId: string) => Promise<void>;
}

// Store owns file data; this hook owns project membership — committed files rendered as their live
// store records (fresh poll status), with in-flight uploads prepended.
export function useProjectFiles(
  projectId: number | null,
  committedFiles: ProjectFile[] | null | undefined,
): UseProjectFiles {
  const queryClient = useQueryClient();
  const serverUrl = useSession((state) => state.serverUrl);
  const upload = useUpload();

  const target = useMemo<UploadTarget | null>(
    () => (projectId == null ? null : { kind: "project", projectId }),
    [projectId],
  );

  // Seed the store from the committed list; clears finished uploads so they can't resurrect as phantom optimistic rows.
  const upsert = useUserFileStore((state) => state.upsert);
  useEffect(() => {
    if (projectId != null && committedFiles) {
      upsert(committedFiles, { kind: "project", projectId });
    }
  }, [projectId, committedFiles, upsert]);

  const committed = useLiveFiles(committedFiles ?? EMPTY_FILES);

  const optimisticIds = useUserFileStore(
    useShallow((state) =>
      projectId == null
        ? EMPTY_IDS
        : Object.values(state.tasksById)
            .filter(
              (task) =>
                task.target.kind === "project" &&
                task.target.projectId === projectId,
            )
            .map((task) => task.clientId),
    ),
  );
  const optimistic = useFilesByIds(optimisticIds);

  const files = useMemo(() => {
    const committedFileIds = new Set(committed.map((file) => file.id));
    const optimisticOnly = optimistic.filter(
      (file) => !committedFileIds.has(file.id),
    );
    return [...optimisticOnly, ...committed];
  }, [optimistic, committed]);

  const runPicked = useCallback(
    async (pick: () => Promise<NormalizedAsset[]>) => {
      if (target != null) await upload.pickAndUpload(pick, target);
    },
    [target, upload],
  );

  const addDocuments = useCallback(() => runPicked(pickDocuments), [runPicked]);
  const addImages = useCallback(() => runPicked(pickImages), [runPicked]);

  const invalidateProject = useCallback(
    () =>
      queryClient.invalidateQueries({
        queryKey: QUERY_KEYS.userProject(serverUrl, projectId),
      }),
    [queryClient, serverUrl, projectId],
  );

  const linkRecent = useCallback(
    async (fileId: string) => {
      if (projectId == null) return;
      try {
        await linkFileToProject(projectId, fileId);
        await invalidateProject();
      } catch (error) {
        console.warn("link file to project failed", error);
        toast.error(getErrorMessage(error, "Couldn't add that file."));
      }
    },
    [projectId, invalidateProject],
  );

  const removeFile = useCallback(
    async (fileId: string) => {
      if (projectId == null) return;
      // An in-flight upload is keyed by a client temp id and isn't on the server yet — cancel it
      // locally; unlinking would send the temp id to the server (4xx) and leave the chip stuck.
      const store = useUserFileStore.getState();
      if (store.tasksById[fileId]?.status === "uploading") {
        store.removeFile(fileId, { kind: "project", projectId });
        return;
      }
      try {
        await unlinkFileFromProject(projectId, fileId);
        await invalidateProject();
      } catch (error) {
        console.warn("unlink file from project failed", error);
        toast.error(getErrorMessage(error, "Couldn't remove that file."));
      }
    },
    [projectId, invalidateProject],
  );

  return {
    files,
    addDocuments,
    addImages,
    linkRecent,
    removeFile,
  };
}
