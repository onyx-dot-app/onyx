"use client";
import React, {
  createContext,
  useState,
  useContext,
  useMemo,
  useEffect,
} from "react";
import { Persona } from "@/app/admin/assistants/interfaces";
import {
  classifyAssistants,
  orderAssistantsForUser,
  getUserCreatedAssistants,
} from "@/lib/assistants/utils";
import { useUser } from "../user/UserProvider";

interface AssistantsContextProps {
  assistants: Persona[];
  visibleAssistants: Persona[];
  hiddenAssistants: Persona[];
  finalAssistants: Persona[];
  ownedButHiddenAssistants: Persona[];
  refreshAssistants: () => Promise<void>;

  // Admin only
  editablePersonas: Persona[];
  allAssistants: Persona[];
}

const AssistantsContext = createContext<AssistantsContextProps | undefined>(
  undefined
);

export const AssistantsProvider: React.FC<{
  children: React.ReactNode;
  initialAssistants: Persona[];
  hasAnyConnectors: boolean;
  hasImageCompatibleModel: boolean;
}> = ({
  children,
  initialAssistants,
  hasAnyConnectors,
  hasImageCompatibleModel,
}) => {
  const [assistants, setAssistants] = useState<Persona[]>(
    initialAssistants || []
  );
  const { user, isLoadingUser, isAdmin } = useUser();
  const [editablePersonas, setEditablePersonas] = useState<Persona[]>([]);

  useEffect(() => {
    const fetchEditablePersonas = async () => {
      if (!isAdmin) {
        return;
      }

      try {
        const response = await fetch("/api/admin/persona?get_editable=true");
        if (!response.ok) {
          console.error("Failed to fetch editable personas");
          return;
        }
        const personas = await response.json();
        setEditablePersonas(personas);
      } catch (error) {
        console.error("Error fetching editable personas:", error);
      }
    };

    fetchEditablePersonas();
  }, [isAdmin]);

  const [allAssistants, setAllAssistants] = useState<Persona[]>([]);

  useEffect(() => {
    const fetchAllAssistants = async () => {
      if (!isAdmin) {
        return;
      }

      try {
        const response = await fetch("/api/admin/persona");
        if (!response.ok) {
          console.error("Failed to fetch all personas");
          return;
        }
        const personas = await response.json();
        setAllAssistants(personas);
      } catch (error) {
        console.error("Error fetching all personas:", error);
      }
    };

    fetchAllAssistants();
  }, [isAdmin]);

  const refreshAssistants = async () => {
    try {
      const response = await fetch("/api/persona", {
        method: "GET",
        headers: {
          "Content-Type": "application/json",
        },
      });
      if (!response.ok) throw new Error("Failed to fetch assistants");
      let assistants: Persona[] = await response.json();
      if (!hasImageCompatibleModel) {
        assistants = assistants.filter(
          (assistant) =>
            !assistant.tools.some(
              (tool) => tool.in_code_tool_id === "ImageGenerationTool"
            )
        );
      }
      if (!hasAnyConnectors) {
        assistants = assistants.filter(
          (assistant) => assistant.num_chunks === 0
        );
      }
      setAssistants(assistants);
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
  }, [user, assistants, isLoadingUser]);

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
