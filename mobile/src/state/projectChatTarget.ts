// Non-persisted store carrying "the next new chat belongs to this project" across
// navigation. Web reads `?projectId` from the URL; mobile is route-based, so the
// project screen sets it here, ensureSession reads/clears it on lazy create, and
// useStartNewChat clears it so a plain "New Chat" never inherits a stale project.
import { create } from "zustand";

interface ProjectChatTargetStore {
  projectId: number | null;
  setProjectId: (projectId: number | null) => void;
  clear: () => void;
}

export const useProjectChatTarget = create<ProjectChatTargetStore>((set) => ({
  projectId: null,
  setProjectId: (projectId) => set({ projectId }),
  clear: () => set({ projectId: null }),
}));
