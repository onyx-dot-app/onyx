// projectChatTarget — a tiny, NON-persisted store that carries "the next new
// chat should be created inside this project" across the navigation from the
// project detail screen to the single chat screen.
//
// Web binds a chat to a project by passing `project_id` to create-chat-session
// while `?projectId` is in the URL. Mobile is route-based: the project screen's
// composer launcher sets `projectId` here, then navigates to the chat screen.
// `useChatSessionLifecycle.ensureSession` reads it when lazily creating the
// backend session and clears it afterward. `useStartNewChat` clears it too, so a
// plain "New Chat" never inherits a stale project.
import { create } from "zustand";

interface ProjectChatTargetStore {
  /** The project a freshly-created chat should be linked to, or null. */
  projectId: number | null;
  setProjectId: (projectId: number | null) => void;
  clear: () => void;
}

export const useProjectChatTarget = create<ProjectChatTargetStore>((set) => ({
  projectId: null,
  setProjectId: (projectId) => set({ projectId }),
  clear: () => set({ projectId: null }),
}));
