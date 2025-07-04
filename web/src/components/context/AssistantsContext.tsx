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
import {
  MinimalPersonaSnapshot,
  Persona,
} from "@/app/admin/assistants/interfaces";
import {
  classifyAssistants,
  orderAssistantsForUser,
  getUserCreatedAssistants,
  filterAssistants,
} from "@/lib/assistants/utils";
import { useUser } from "../user/UserProvider";

interface AssistantsContextProps {
  assistants: MinimalPersonaSnapshot[];
  visibleAssistants: MinimalPersonaSnapshot[];
  hiddenAssistants: MinimalPersonaSnapshot[];
  finalAssistants: MinimalPersonaSnapshot[];
  ownedButHiddenAssistants: MinimalPersonaSnapshot[];
  refreshAssistants: () => Promise<void>;
  isImageGenerationAvailable: boolean;
  // Admin only
  editablePersonas: MinimalPersonaSnapshot[];
  allAssistants: MinimalPersonaSnapshot[];
  pinnedAssistants: MinimalPersonaSnapshot[];
  setPinnedAssistants: Dispatch<SetStateAction<MinimalPersonaSnapshot[]>>;
}

const AssistantsContext = createContext<AssistantsContextProps | undefined>(
  undefined
);

export const AssistantsProvider: React.FC<{
  children: React.ReactNode;
  initialAssistants: MinimalPersonaSnapshot[];
}> = ({ children, initialAssistants }) => {
  const [assistants, setAssistants] = useState<MinimalPersonaSnapshot[]>(
    initialAssistants || []
  );
  const { user, isAdmin, isCurator } = useUser();
  const [editablePersonas, setEditablePersonas] = useState<
    MinimalPersonaSnapshot[]
  >([]);
  const [allAssistants, setAllAssistants] = useState<MinimalPersonaSnapshot[]>(
    []
  );

  const [pinnedAssistants, setPinnedAssistants] = useState<
    MinimalPersonaSnapshot[]
  >(() => {
    if (user?.preferences.pinned_assistants) {
      return user.preferences.pinned_assistants
        .map((id) => assistants.find((assistant) => assistant.id === id))
        .filter(
          (assistant): assistant is MinimalPersonaSnapshot =>
            assistant !== undefined
        );
    } else {
      return assistants.filter((a) => a.is_default_persona);
    }
  });

  useEffect(() => {
    setPinnedAssistants(() => {
      if (user?.preferences.pinned_assistants) {
        return user.preferences.pinned_assistants
          .map((id) => assistants.find((assistant) => assistant.id === id))
          .filter(
            (assistant): assistant is MinimalPersonaSnapshot =>
              assistant !== undefined
          );
      } else {
        return assistants.filter((a) => a.is_default_persona);
      }
    });
  }, [user?.preferences?.pinned_assistants, assistants]);

  const [isImageGenerationAvailable, setIsImageGenerationAvailable] =
    useState<boolean>(false);

  useEffect(() => {
    const checkImageGenerationAvailability = async () => {
      try {
        const response = await fetch("/api/persona/image-generation-tool");
        if (response.ok) {
          const { is_available } = await response.json();
          setIsImageGenerationAvailable(is_available);
        }
      } catch (error) {
        console.error("Error checking image generation availability:", error);
      }
    };

    checkImageGenerationAvailability();
  }, []);

  const fetchPersonas = async () => {
    if (!isAdmin && !isCurator) {
      return;
    }

    try {
      const [editableResponse, allResponse] = await Promise.all([
        fetch("/api/admin/persona?get_editable=true"),
        fetch("/api/admin/persona"),
      ]);

      if (editableResponse.ok) {
        const editablePersonas = await editableResponse.json();
        setEditablePersonas(editablePersonas);
      }

      if (allResponse.ok) {
        const allPersonas = await allResponse.json();
        setAllAssistants(allPersonas);
      } else {
        console.error("Error fetching personas:", allResponse);
      }
    } catch (error) {
      console.error("Error fetching personas:", error);
    }
  };

  useEffect(() => {
    fetchPersonas();
  }, [isAdmin, isCurator]);

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

      let filteredAssistants = filterAssistants(assistants);

      setAssistants(filteredAssistants);

      // Fetch and update allAssistants for admins and curators
      await fetchPersonas();
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
      assistants
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
        editablePersonas,
        allAssistants,
        isImageGenerationAvailable,
        setPinnedAssistants,
        pinnedAssistants,
      }}
    >
      {children}
    </AssistantsContext.Provider>
  );
};

export const useAssistants = (): AssistantsContextProps => {
  const context = useContext(AssistantsContext);
  if (!context) {
    throw new Error("useAssistants must be used within an AssistantsProvider");
  }
  return context;
};
