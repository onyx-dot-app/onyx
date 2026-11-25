"use client";

import { useMemo } from "react";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { useUser } from "@/providers/UserProvider";
import useChatSessions from "@/hooks/useChatSessions";
import { useAppPosition } from "@/lib/navigation/hooks";
import {
  adjacentChatId,
  markRecentChatShortcutTarget,
  toggleModelPicker,
} from "@/lib/shortcuts/utils";

export interface ChatShortcutActions {
  newChat: () => void;
  resetNewSession: () => void;
  toggleModelPicker: () => void;
  previousChat: () => void;
  nextChat: () => void;
  /** Opens the chat at `index` (0-based) in the sidebar's Recents list. */
  jumpToChat: (index: number) => void;
}

/** The actions behind the chat shortcuts. */
export function useChatShortcutActions(): ChatShortcutActions {
  const appPosition = useAppPosition();
  const { chatSessions } = useChatSessions();
  const { reset, setAppMode } = useQueryController();
  const { user } = useUser();
  const defaultMode =
    user?.preferences?.default_app_mode?.toLowerCase() === "search"
      ? "search"
      : "chat";

  return useMemo(() => {
    const chatIds = chatSessions.map((session) => session.id);
    function openChat(chatId: string | null | undefined) {
      if (!chatId || chatId === appPosition.chat()) return;
      markRecentChatShortcutTarget(chatId);
      appPosition.openChat(chatId);
    }
    function resetNewSession() {
      if (!appPosition.isNewSession()) return;
      setAppMode(defaultMode);
      reset();
    }
    return {
      newChat: () => {
        resetNewSession();
        appPosition.openNewSession();
      },
      resetNewSession,
      toggleModelPicker,
      previousChat: () =>
        openChat(adjacentChatId(chatIds, appPosition.chat(), -1)),
      nextChat: () => openChat(adjacentChatId(chatIds, appPosition.chat(), 1)),
      jumpToChat: (index) => openChat(chatIds[index]),
    };
  }, [appPosition, chatSessions, defaultMode, reset, setAppMode]);
}
