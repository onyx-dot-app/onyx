"use client";

import React from "react";
import { toast } from "@/hooks/useToast";
import { ChatSession } from "@/app/app/interfaces";
import { LOCAL_STORAGE_KEYS } from "@/lib/sidebar/constants";

export interface MoveOperationParams {
  chatSession: ChatSession;
  targetProjectId: number;
  refreshChatSessions: () => Promise<any>;
  refreshCurrentProjectDetails: () => Promise<any>;
  fetchProjects: () => Promise<any>;
  currentProjectId: number | null;
}

export const shouldShowMoveModal = (chatSession: ChatSession): boolean => {
  const hideModal =
    typeof window !== "undefined" &&
    window.localStorage.getItem(
      LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL
    ) === "true";

  return !hideModal && chatSession.persona_id !== 0;
};

export const showErrorNotification = (message: string) => {
  toast.error(message);
};

function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

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
