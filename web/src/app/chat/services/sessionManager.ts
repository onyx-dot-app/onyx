import { Persona } from "../../admin/assistants/interfaces";
import { LlmDescriptor } from "@/lib/hooks";
import { structureValue } from "@/lib/llm/utils";
import { createChatSession, updateLlmOverrideForChatSession } from "../lib";

export interface SessionManagerDependencies {
  liveAssistant: Persona | undefined;
  searchParams: URLSearchParams | null;
  llmManager: { currentLlm: LlmDescriptor };
  chatSessionIdRef: React.MutableRefObject<string | null>;
  updateStatesWithNewSessionId: (newSessionId: string) => void;
  setAbortControllers: React.Dispatch<
    React.SetStateAction<Map<string | null, AbortController>>
  >;
}

export interface SessionSetupResult {
  sessionId: string;
  isNewSession: boolean;
  controller: AbortController;
}

export class SessionManager {
  constructor(private deps: SessionManagerDependencies) {}

  async setupSession(
    modelOverride?: LlmDescriptor,
    searchParamBasedChatSessionName?: string | null
  ): Promise<SessionSetupResult> {
    const {
      liveAssistant,
      searchParams,
      llmManager,
      chatSessionIdRef,
      updateStatesWithNewSessionId,
      setAbortControllers,
    } = this.deps;

    let currChatSessionId: string;
    const isNewSession = chatSessionIdRef.current === null;

    if (isNewSession) {
      currChatSessionId = await createChatSession(
        liveAssistant?.id || 0,
        searchParamBasedChatSessionName || null
      );
    } else {
      currChatSessionId = chatSessionIdRef.current as string;
    }

    // Update model override for the chat session
    const finalLLM = modelOverride || llmManager.currentLlm;
    updateLlmOverrideForChatSession(
      currChatSessionId,
      structureValue(
        finalLLM.name || "",
        finalLLM.provider || "",
        finalLLM.modelName || ""
      )
    );

    updateStatesWithNewSessionId(currChatSessionId);

    const controller = new AbortController();
    setAbortControllers((prev) => {
      const newMap = new Map(prev);
      newMap.set(currChatSessionId, controller);
      return newMap;
    });

    return {
      sessionId: currChatSessionId,
      isNewSession,
      controller,
    };
  }
}
