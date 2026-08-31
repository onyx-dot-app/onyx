import { useCallback, useEffect, useRef, useState } from "react";

import type { ModelOption } from "@/chat/models";

interface UseSelectedModelArgs {
  chatSessionId: string | null;
  // undefined = unresolved (agents loading, or a new session missing from the sessions list).
  agentId: number | undefined;
  // Crossing this boundary releases the pick.
  projectId: number | null;
}

export interface SelectedModel {
  // null = no explicit pick, so the agent's own default model applies.
  selectedModel: ModelOption | null;
  selectModel: (model: ModelOption | null) => void;
}

/*
 * The model the next send runs on, held per conversation and reset on the same rules as
 * useDeepResearchToggle. Switching to a null session id and back is the send that created the
 * conversation, not a move to a different one, so clearing on it would drop the model that send
 * just used.
 */
export function useSelectedModel({
  chatSessionId,
  agentId,
  projectId,
}: UseSelectedModelArgs): SelectedModel {
  const [selectedModel, setSelectedModel] = useState<ModelOption | null>(null);
  const previousChatSessionId = useRef<string | null>(chatSessionId);
  const previousAgentId = useRef<number | undefined>(agentId);
  const previousProjectId = useRef<number | null>(projectId);

  useEffect(() => {
    const previousId = previousChatSessionId.current;
    previousChatSessionId.current = chatSessionId;
    if (previousId !== null && previousId !== chatSessionId) {
      setSelectedModel(null);
    }
  }, [chatSessionId]);

  // Only a move between two known agents counts as a switch. The unresolved gap after a send is
  // not an agent change, and treating it as one would clear the pick mid-send.
  useEffect(() => {
    if (agentId === undefined) return;
    const previousId = previousAgentId.current;
    previousAgentId.current = agentId;
    if (previousId !== undefined && previousId !== agentId) {
      setSelectedModel(null);
    }
  }, [agentId]);

  /*
   * Two project landing composers both sit on a null session id and the default agent, so neither
   * reset above fires between them and the pick would follow the user into the next project. No
   * unresolved-value guard is needed here: the send reads its options before the route flips, so
   * every project change is a real one.
   */
  useEffect(() => {
    const previousId = previousProjectId.current;
    previousProjectId.current = projectId;
    if (previousId !== projectId) setSelectedModel(null);
  }, [projectId]);

  const selectModel = useCallback(
    (model: ModelOption | null) => setSelectedModel(model),
    [],
  );

  return { selectedModel, selectModel };
}
