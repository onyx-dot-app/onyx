import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useCallback, useMemo, useState } from "react";
import { ChatSession } from "../interfaces";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "../services/searchParams";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { useAgentsContext } from "@/contexts/AgentsContext";

export function useAssistantController({
  selectedChatSession,
  onAssistantSelect,
}: {
  selectedChatSession: ChatSession | null | undefined;
  onAssistantSelect?: () => void;
}) {
  const searchParams = useSearchParams();
  const { agents: availableAssistants, pinnedAgents: pinnedAssistants } =
    useAgentsContext();
  const combinedSettings = useSettingsContext();

  const defaultAssistantIdRaw = searchParams?.get(
    SEARCH_PARAM_NAMES.PERSONA_ID
  );
  const defaultAssistantId = defaultAssistantIdRaw
    ? parseInt(defaultAssistantIdRaw)
    : undefined;

  const existingChatSessionAssistantId = selectedChatSession?.persona_id;
  const [selectedAssistant, setSelectedAssistant] = useState<
    MinimalPersonaSnapshot | undefined
  >(
    // NOTE: look through available assistants here, so that even if the user
    // has hidden this assistant it still shows the correct assistant when
    // going back to an old chat session
    existingChatSessionAssistantId !== undefined
      ? availableAssistants.find(
          (assistant) => assistant.id === existingChatSessionAssistantId
        )
      : defaultAssistantId !== undefined
        ? availableAssistants.find(
            (assistant) => assistant.id === defaultAssistantId
          )
        : undefined
  );

  // Current assistant is decided based on this ordering
  // 1. Alternative assistant (assistant selected explicitly by user)
  // 2. Selected assistant (assistant default in this chat session)
  // 3. Unified assistant (ID 0) if available (unless disabled)
  // 4. First pinned assistants (ordered list of pinned assistants)
  // 5. Available assistants (ordered list of available assistants)
  // Relevant test: `live_assistant.spec.ts`
  const liveAssistant: MinimalPersonaSnapshot | undefined = useMemo(() => {
    if (selectedAssistant) return selectedAssistant;

    const disableDefaultAssistant =
      combinedSettings?.settings?.disable_default_assistant ?? false;

    if (disableDefaultAssistant) {
      // Skip unified assistant (ID 0), go straight to pinned/available
      // Filter out ID 0 from both pinned and available assistants
      const nonDefaultPinned = pinnedAssistants.filter((a) => a.id !== 0);
      const nonDefaultAvailable = availableAssistants.filter((a) => a.id !== 0);

      return (
        nonDefaultPinned[0] || nonDefaultAvailable[0] || availableAssistants[0] // Last resort fallback
      );
    }

    // Try to use the unified assistant (ID 0) as default
    const unifiedAssistant = availableAssistants.find((a) => a.id === 0);
    if (unifiedAssistant) return unifiedAssistant;

    // Fall back to pinned or available assistants
    return pinnedAssistants[0] || availableAssistants[0];
  }, [
    selectedAssistant,
    pinnedAssistants,
    availableAssistants,
    combinedSettings,
  ]);

  const setSelectedAssistantFromId = useCallback(
    (assistantId: number | null | undefined) => {
      // NOTE: also intentionally look through available assistants here, so that
      // even if the user has hidden an assistant they can still go back to it
      // for old chats
      let newAssistant =
        assistantId !== null
          ? availableAssistants.find(
              (assistant) => assistant.id === assistantId
            )
          : undefined;

      // if no assistant was passed in / found, use the default assistant
      if (!newAssistant && defaultAssistantId !== undefined) {
        newAssistant = availableAssistants.find(
          (assistant) => assistant.id === defaultAssistantId
        );
      }

      setSelectedAssistant(newAssistant);
      onAssistantSelect?.();
    },
    [availableAssistants, defaultAssistantId, onAssistantSelect]
  );

  return {
    // main assistant selection
    selectedAssistant,
    setSelectedAssistantFromId,

    // final computed assistant
    liveAssistant,
  };
}
