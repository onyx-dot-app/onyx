import { useState, useMemo } from "react";
import { Persona } from "../../admin/assistants/interfaces";
import { useAssistants } from "@/components/context/AssistantsContext";

export interface UseAssistantManagementProps {
  existingChatSessionAssistantId?: number;
  defaultAssistantId?: number;
}

export function useAssistantManagement({
  existingChatSessionAssistantId,
  defaultAssistantId,
}: UseAssistantManagementProps) {
  const { assistants: availableAssistants, pinnedAssistants } = useAssistants();

  const [selectedAssistant, setSelectedAssistant] = useState<
    Persona | undefined
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

  const setSelectedAssistantFromId = (assistantId: number) => {
    // NOTE: also intentionally look through available assistants here, so that
    // even if the user has hidden an assistant they can still go back to it
    // for old chats
    setSelectedAssistant(
      availableAssistants.find((assistant) => assistant.id === assistantId)
    );
  };

  // UI STATE: Alternative assistant selection (for @mentions and switching assistants)
  const [alternativeAssistant, setAlternativeAssistant] =
    useState<Persona | null>(null);

  // Current assistant is decided based on this ordering
  // 1. Alternative assistant (assistant selected explicitly by user)
  // 2. Selected assistant (assistant default in this chat session)
  // 3. First pinned assistants (ordered list of pinned assistants)
  // 4. Available assistants (ordered list of available assistants)
  // Relevant test: `live_assistant.spec.ts`
  const liveAssistant = useMemo(
    () =>
      alternativeAssistant ||
      selectedAssistant ||
      pinnedAssistants[0] ||
      availableAssistants[0],
    [
      alternativeAssistant,
      selectedAssistant,
      pinnedAssistants,
      availableAssistants,
    ]
  );

  const noAssistants = liveAssistant == null || liveAssistant == undefined;

  // this is used to track which assistant is being used to generate the current message
  // for example, this would come into play when:
  // 1. default assistant is `Onyx`
  // 2. we "@"ed the `GPT` assistant and sent a message
  // 3. while the `GPT` assistant message is generating, we "@" the `Paraphrase` assistant
  // UI STATE: Currently generating assistant (tracks which assistant is actively responding)
  const [alternativeGeneratingAssistant, setAlternativeGeneratingAssistant] =
    useState<Persona | null>(null);

  return {
    selectedAssistant,
    setSelectedAssistant,
    setSelectedAssistantFromId,
    alternativeAssistant,
    setAlternativeAssistant,
    liveAssistant,
    noAssistants,
    alternativeGeneratingAssistant,
    setAlternativeGeneratingAssistant,
    availableAssistants,
    pinnedAssistants,
  };
}
