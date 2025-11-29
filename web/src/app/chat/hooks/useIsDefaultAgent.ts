import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "../services/searchParams";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { ChatSession } from "../interfaces";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { DEFAULT_ASSISTANT_ID } from "@/lib/constants";

/**
 * Determines if the current assistant is the default agent based on:
 * 1. Whether default agent is disabled in settings
 * 2. If URL has an assistantId specified
 * 3. Based on the current chat session
 */
export function useIsDefaultAgent({
  liveAssistant,
  existingChatSessionId,
  selectedChatSession,
  settings,
}: {
  liveAssistant: MinimalPersonaSnapshot | undefined;
  existingChatSessionId: string | null;
  selectedChatSession: ChatSession | undefined;
  settings: CombinedSettings | null;
}) {
  const searchParams = useSearchParams();
  const urlAssistantId = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);

  return useMemo(() => {
    // If default assistant is disabled, it can never be the default agent
    if (settings?.settings?.disable_default_assistant) {
      return false;
    }

    // If URL has an assistantId, it's explicitly selected, not default
    if (
      urlAssistantId !== undefined &&
      urlAssistantId !== DEFAULT_ASSISTANT_ID.toString()
    ) {
      return false;
    }

    // If there's an existing chat session with a persona_id, it's not default
    if (
      existingChatSessionId &&
      selectedChatSession?.persona_id !== DEFAULT_ASSISTANT_ID
    ) {
      return false;
    }

    // If just on `/chat` page, it's the default agent
    return true;
  }, [
    settings?.settings?.disable_default_assistant,
    urlAssistantId,
    existingChatSessionId,
    selectedChatSession?.persona_id,
    liveAssistant?.id,
  ]);
}
