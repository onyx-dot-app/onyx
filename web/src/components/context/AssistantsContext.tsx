"use client";
import React, {
  createContext,
  useState,
  useContext,
  useMemo,
  useEffect,
  SetStateAction,
  Dispatch,
} from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import {
  classifyAssistants,
  orderAssistantsForUser,
  getUserCreatedAssistants,
  filterAssistants,
} from "@/lib/assistants/utils";
import { useUser } from "../user/UserProvider";
import {
  UserSpecificAssistantPreference,
  UserSpecificAssistantPreferences,
} from "@/lib/types";
import { useAssistantPreferences } from "@/app/chat/hooks/useAssistantPreferences";

interface AssistantsContextProps {
  assistants: MinimalPersonaSnapshot[];
  visibleAssistants: MinimalPersonaSnapshot[];
  hiddenAssistants: MinimalPersonaSnapshot[];
  finalAssistants: MinimalPersonaSnapshot[];
  ownedButHiddenAssistants: MinimalPersonaSnapshot[];
  refreshAssistants: () => Promise<void>;

  // assistants that the user has explicitly pinned
  pinnedAssistants: MinimalPersonaSnapshot[];
  setPinnedAssistants: Dispatch<SetStateAction<MinimalPersonaSnapshot[]>>;

  assistantPreferences: UserSpecificAssistantPreferences | null;
  setSpecificAssistantPreferences: (
    assistantId: number,
    assistantPreferences: UserSpecificAssistantPreference
  ) => void;

  forcedToolIds: number[];
  setForcedToolIds: Dispatch<SetStateAction<number[]>>;
}

const AssistantsContext = createContext<AssistantsContextProps | undefined>(
  undefined
);

export const AssistantsProvider: React.FC<{
  children: React.ReactNode;
  initialAssistants: MinimalPersonaSnapshot[];
  hasAnyConnectors?: boolean;
  hasImageCompatibleModel?: boolean;
}> = ({ children, initialAssistants }) => {
  const [assistants, setAssistants] = useState<MinimalPersonaSnapshot[]>(
    initialAssistants || []
  );
  const { user } = useUser();
  const { assistantPreferences, setSpecificAssistantPreferences } =
    useAssistantPreferences();
  const [forcedToolIds, setForcedToolIds] = useState<number[]>([]);

  const [pinnedAssistants, setPinnedAssistants] = useState<
    MinimalPersonaSnapshot[]
  >(() => {
    if (user?.preferences.pinned_assistants) {
      return user.preferences.pinned_assistants
        .map((id) => assistants.find((assistant) => assistant.id === id))
        .filter(
          (assistant): assistant is MinimalPersonaSnapshot =>
            assistant !== undefined && assistant.id !== 0
        );
    } else {
      // Filter out the unified assistant (ID 0) from the pinned list
      return assistants.filter((a) => a.is_default_persona && a.id !== 0);
    }
  });

  useEffect(() => {
    setPinnedAssistants(() => {
      if (user?.preferences.pinned_assistants) {
        return user.preferences.pinned_assistants
          .map((id) => assistants.find((assistant) => assistant.id === id))
          .filter(
            (assistant): assistant is MinimalPersonaSnapshot =>
              assistant !== undefined && assistant.id !== 0
          );
      } else {
        // Filter out the unified assistant (ID 0) from the pinned list
        return assistants.filter((a) => a.is_default_persona && a.id !== 0);
      }
    });
  }, [user?.preferences?.pinned_assistants, assistants]);

  const refreshAssistants = async () => {
    try {
      const response = await fetch("/api/persona", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      });
      if (!response.ok) throw new Error("Failed to fetch assistants");
      let assistants: MinimalPersonaSnapshot[] = await response.json();
      setAssistants(filterAssistants(assistants));
    } catch (error) {
      console.error("Error refreshing assistants:", error);
    }
  };

  const {
    visibleAssistants,
    hiddenAssistants,
    finalAssistants,
    ownedButHiddenAssistants,
  } = useMemo(() => {
    const { visibleAssistants, hiddenAssistants } = classifyAssistants(
      user,
      // remove the unified assistant (ID 0) from the list of assistants, it should not be shown
      // anywhere on the chat page
      assistants.filter((assistant) => assistant.id !== 0)
    );

    const finalAssistants = user
      ? orderAssistantsForUser(visibleAssistants, user)
      : visibleAssistants;

    const ownedButHiddenAssistants = getUserCreatedAssistants(
      user,
      hiddenAssistants
    );

    return {
      visibleAssistants,
      hiddenAssistants,
      finalAssistants,
      ownedButHiddenAssistants,
    };
  }, [user, assistants]);

  return (
    <AssistantsContext.Provider
      value={{
        assistants,
        visibleAssistants,
        hiddenAssistants,
        finalAssistants,
        ownedButHiddenAssistants,
        refreshAssistants,
        setPinnedAssistants,
        pinnedAssistants,
        assistantPreferences,
        setSpecificAssistantPreferences,
        forcedToolIds,
        setForcedToolIds,
      }}
    >
      {children}
    </AssistantsContext.Provider>
  );
};

export const useAssistantsContext = (): AssistantsContextProps => {
  const context = useContext(AssistantsContext);
  if (!context) {
    throw new Error("useAssistants must be used within an AssistantsProvider");
  }
  return context;
};
