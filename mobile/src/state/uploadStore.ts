// Ephemeral per-project upload state (optimistic files + progress + errors). Never
// persisted; a new Map per write so selectors re-render.
import { create } from "zustand";

import type { ProjectFile } from "@/chat/contracts/projects";

export interface OptimisticUpload {
  file: ProjectFile; // status UPLOADING; `id` === temp id
  progress: number; // 0..1
}

export interface ProjectUploads {
  uploads: Map<string, OptimisticUpload>; // keyed by temp id
  errors: string[];
}

interface UploadStore {
  byProject: Map<number, ProjectUploads>;
  begin: (projectId: number, files: ProjectFile[]) => void;
  setProgress: (projectId: number, tempId: string, progress: number) => void;
  finish: (projectId: number, tempId: string) => void;
  setErrors: (projectId: number, errors: string[]) => void;
  clearErrors: (projectId: number) => void;
}

function emptyProject(): ProjectUploads {
  return { uploads: new Map(), errors: [] };
}

function writeProject(
  byProject: Map<number, ProjectUploads>,
  projectId: number,
  patch: Partial<ProjectUploads>,
): Map<number, ProjectUploads> {
  const next = new Map(byProject);
  const current = next.get(projectId) ?? emptyProject();
  next.set(projectId, { ...current, ...patch });
  return next;
}

export const useUploadStore = create<UploadStore>((set, get) => ({
  byProject: new Map(),

  begin: (projectId, files) =>
    set((state) => {
      const uploads = new Map(
        state.byProject.get(projectId)?.uploads ?? new Map(),
      );
      files.forEach((file) => uploads.set(file.id, { file, progress: 0 }));
      return {
        byProject: writeProject(state.byProject, projectId, {
          uploads,
          errors: [],
        }),
      };
    }),

  setProgress: (projectId, tempId, progress) =>
    set((state) => {
      const current = state.byProject.get(projectId)?.uploads.get(tempId);
      if (!current) return {};
      const uploads = new Map(state.byProject.get(projectId)?.uploads);
      uploads.set(tempId, { ...current, progress });
      return {
        byProject: writeProject(state.byProject, projectId, { uploads }),
      };
    }),

  finish: (projectId, tempId) =>
    set((state) => {
      const existing = state.byProject.get(projectId);
      if (!existing?.uploads.has(tempId)) return {};
      const uploads = new Map(existing.uploads);
      uploads.delete(tempId);
      return {
        byProject: writeProject(state.byProject, projectId, { uploads }),
      };
    }),

  setErrors: (projectId, errors) =>
    set((state) => ({
      byProject: writeProject(state.byProject, projectId, { errors }),
    })),

  clearErrors: (projectId) => {
    if ((get().byProject.get(projectId)?.errors.length ?? 0) === 0) return;
    set((state) => ({
      byProject: writeProject(state.byProject, projectId, { errors: [] }),
    }));
  },
}));

// Project-keyed, so a projectId switch reads a different bucket (no cross-conversation leak).
export function useProjectUploads(
  projectId: number | null,
): ProjectUploads | undefined {
  return useUploadStore((state) =>
    projectId == null ? undefined : state.byProject.get(projectId),
  );
}
