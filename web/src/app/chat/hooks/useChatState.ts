import { useState, useCallback } from "react";
import { ChatState, RegenerationState } from "../types";

// ===== TYPES =====

interface ChatStateHookReturn {
  // State
  chatState: Map<string | null, ChatState>;
  regenerationState: Map<string | null, RegenerationState | null>;
  abortControllers: Map<string | null, AbortController>;
  canContinue: Map<string | null, boolean>;

  // Current session getters
  getCurrentChatState: () => ChatState;
  getCurrentRegenerationState: () => RegenerationState | null;
  getCurrentCanContinue: () => boolean;
  getCurrentChatAnswering: () => boolean;

  // State updaters
  updateChatState: (newState: ChatState, sessionId?: string | null) => void;
  updateRegenerationState: (
    newState: RegenerationState | null,
    sessionId?: string | null
  ) => void;
  updateCanContinue: (newState: boolean, sessionId?: string | null) => void;
  resetRegenerationState: (sessionId?: string | null) => void;

  // Session management
  updateStatesWithNewSessionId: (newSessionId: string) => void;

  // Abort controller management
  setAbortControllers: React.Dispatch<
    React.SetStateAction<Map<string | null, AbortController>>
  >;
}

// ===== HOOK IMPLEMENTATION =====

export function useChatState(
  currentSessionId: () => string,
  firstMessage?: string
): ChatStateHookReturn {
  // ===== STATE DEFINITIONS =====

  // Chat interaction states (loading, streaming, input, etc.)
  const [chatState, setChatState] = useState<Map<string | null, ChatState>>(
    new Map([[null, firstMessage ? "loading" : "input"]])
  );

  // Regeneration state management
  const [regenerationState, setRegenerationState] = useState<
    Map<string | null, RegenerationState | null>
  >(new Map([[null, null]]));

  // Abort controllers for each session
  const [abortControllers, setAbortControllers] = useState<
    Map<string | null, AbortController>
  >(new Map());

  // Continue generation capability
  const [canContinue, setCanContinue] = useState<Map<string | null, boolean>>(
    new Map([[null, false]])
  );

  // ===== STATE UPDATERS =====

  const updateChatState = useCallback(
    (newState: ChatState, sessionId?: string | null) => {
      setChatState((prevState) => {
        const newChatState = new Map(prevState);
        newChatState.set(
          sessionId !== undefined ? sessionId : currentSessionId(),
          newState
        );
        return newChatState;
      });
    },
    [currentSessionId]
  );

  const updateRegenerationState = useCallback(
    (newState: RegenerationState | null, sessionId?: string | null) => {
      setRegenerationState((prevState) => {
        const newRegenerationState = new Map(prevState);
        newRegenerationState.set(
          sessionId !== undefined && sessionId != null
            ? sessionId
            : currentSessionId(),
          newState
        );
        return newRegenerationState;
      });
    },
    [currentSessionId]
  );

  const resetRegenerationState = useCallback(
    (sessionId?: string | null) => {
      updateRegenerationState(null, sessionId);
    },
    [updateRegenerationState]
  );

  const updateCanContinue = useCallback(
    (newState: boolean, sessionId?: string | null) => {
      setCanContinue((prevState) => {
        const newCanContinueState = new Map(prevState);
        newCanContinueState.set(
          sessionId !== undefined ? sessionId : currentSessionId(),
          newState
        );
        return newCanContinueState;
      });
    },
    [currentSessionId]
  );

  // ===== CURRENT SESSION GETTERS =====

  const getCurrentChatState = useCallback((): ChatState => {
    return chatState.get(currentSessionId()) || "input";
  }, [chatState, currentSessionId]);

  const getCurrentRegenerationState =
    useCallback((): RegenerationState | null => {
      return regenerationState.get(currentSessionId()) || null;
    }, [regenerationState, currentSessionId]);

  const getCurrentCanContinue = useCallback((): boolean => {
    return canContinue.get(currentSessionId()) || false;
  }, [canContinue, currentSessionId]);

  const getCurrentChatAnswering = useCallback(() => {
    return (
      getCurrentChatState() == "toolBuilding" ||
      getCurrentChatState() == "streaming" ||
      getCurrentChatState() == "loading"
    );
  }, [getCurrentChatState]);

  // ===== SESSION MANAGEMENT =====

  const updateStatesWithNewSessionId = useCallback((newSessionId: string) => {
    const updateState = (
      setState: React.Dispatch<React.SetStateAction<Map<string | null, any>>>,
      defaultValue?: any
    ) => {
      setState((prevState) => {
        const newState = new Map(prevState);
        const existingState = newState.get(null);
        if (existingState !== undefined) {
          newState.set(newSessionId, existingState);
          newState.delete(null);
        } else if (defaultValue !== undefined) {
          newState.set(newSessionId, defaultValue);
        }
        return newState;
      });
    };

    updateState(setRegenerationState);
    updateState(setChatState);
    updateState(setAbortControllers);
  }, []);

  // ===== RETURN OBJECT =====

  return {
    // State
    chatState,
    regenerationState,
    abortControllers,
    canContinue,

    // Current session getters
    getCurrentChatState,
    getCurrentRegenerationState,
    getCurrentCanContinue,
    getCurrentChatAnswering,

    // State updaters
    updateChatState,
    updateRegenerationState,
    updateCanContinue,
    resetRegenerationState,

    // Session management
    updateStatesWithNewSessionId,

    // Abort controller management
    setAbortControllers,
  };
}
