"use client";

import React from "react";
import { toast } from "@/hooks/useToast";
import { ChatSession } from "@/app/app/interfaces";
import { DEFAULT_AGENT_ID } from "@/lib/constants";
import { LOCAL_STORAGE_KEYS } from "@/lib/sidebar/constants";

/** Parameters shared by move-operation helpers. */
export interface MoveOperationParams {
  chatSession: ChatSession;
  targetProjectId: number;
  refreshChatSessions: () => Promise<any>;
  refreshCurrentProjectDetails: () => Promise<any>;
  fetchProjects: () => Promise<any>;
  currentProjectId: number | null;
}

/**
 * Returns `true` when the "move to project" confirmation modal should be shown
 * for the given chat session.
 *
 * The modal is suppressed when the user has previously checked "don't show
 * again" (stored in localStorage) or when the chat is already using the
 * default agent (persona_id === DEFAULT_AGENT_ID), in which case switching
 * projects has no agent-specific implications to warn about.
 */
export const shouldShowMoveModal = (chatSession: ChatSession): boolean => {
  const hideModal =
    typeof window !== "undefined" &&
    window.localStorage.getItem(
      LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
    ) === "true";

  return !hideModal && chatSession.persona_id !== DEFAULT_AGENT_ID;
};

/** Displays a red error toast with the given message. */
export const showErrorNotification = (message: string) => {
  toast.error(message);
};

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Wraps matched substrings of `text` in `<span className="text-text-05">` for
 * highlighting. Unmatched segments are returned as plain strings. Returns the
 * original string unchanged when `query` is empty or produces no match.
 */
export function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query.trim()) return text;

  const escapedQuery = escapeRegex(query.trim());
  const regex = new RegExp(`(${escapedQuery})`, "gi");
  const parts = text.split(regex);

  if (parts.length === 1) return text;

  return parts.map((part, i) =>
    i % 2 === 1
      ? React.createElement("span", { key: i, className: "text-text-05" }, part)
      : React.createElement(React.Fragment, { key: i }, part)
  );
}
