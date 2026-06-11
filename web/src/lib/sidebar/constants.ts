/** Drag-and-drop type identifiers used across the sidebar's DnD contexts. */
export const DRAG_TYPES = {
  /** A chat session being dragged (e.g. into a project folder). */
  CHAT: "chat",
  /** A project folder acting as a drop target. */
  PROJECT: "project",
  /** The Recents section acting as a drop target (removes a chat from a project). */
  RECENTS: "recents",
} as const;

/** localStorage keys used by sidebar components. */
export const LOCAL_STORAGE_KEYS = {
  /**
   * When `"true"`, the "move chat to project" confirmation modal is suppressed
   * and the move proceeds silently.
   */
  HIDE_MOVE_CUSTOM_AGENT_MODAL: "onyx:hideMoveCustomAgentModal",
} as const;
