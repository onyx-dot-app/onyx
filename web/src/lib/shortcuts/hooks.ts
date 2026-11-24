"use client";

import { useMemo } from "react";
import useChatSessions from "@/hooks/useChatSessions";
import { useAppPosition } from "@/lib/navigation/hooks";
import { adjacentChatId, toggleModelPicker } from "@/lib/shortcuts/utils";

export interface ChatShortcutActions {
  newChat: () => void;
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

  return useMemo(() => {
    const chatIds = chatSessions.map((session) => session.id);
    function openChat(chatId: string | null | undefined) {
      if (chatId) appPosition.openChat(chatId);
    }
    return {
      newChat: () => appPosition.openNewSession(),
      toggleModelPicker,
      previousChat: () =>
        openChat(adjacentChatId(chatIds, appPosition.chat(), -1)),
      nextChat: () => openChat(adjacentChatId(chatIds, appPosition.chat(), 1)),
      jumpToChat: (index) => openChat(chatIds[index]),
    };
  }, [appPosition, chatSessions]);
}
