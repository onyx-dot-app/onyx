import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { useCallback, useMemo, useState } from "react";
import { ChatSession } from "../interfaces";
import { useAssistantsContext } from "@/components/context/AssistantsContext";
import { useSearchParams } from "next/navigation";
import { SEARCH_PARAM_NAMES } from "../services/searchParams";

export function useAssistantController({
  selectedChatSession,
}: {
  selectedChatSession: ChatSession | null | undefined;
}) {
  const searchParams = useSearchParams();
  const { assistants: availableAssistants, pinnedAssistants } =
    useAssistantsContext();

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
  // 2. Selected assistant (assistnat default in this chat session)
  // 3. First pinned assistants (ordered list of pinned assistants)
  // 4. Available assistants (ordered list of available assistants)
  // Relevant test: `live_assistant.spec.ts`
  const liveAssistant: MinimalPersonaSnapshot | undefined = useMemo(
    () => selectedAssistant || pinnedAssistants[0] || availableAssistants[0],
    [selectedAssistant, pinnedAssistants, availableAssistants]
  );

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
    },
    [availableAssistants, defaultAssistantId]
  );

  return {
    // main assistant selection
    selectedAssistant,
    setSelectedAssistantFromId,

    // final computed assistant
    liveAssistant,
  };
}
