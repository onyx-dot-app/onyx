"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { MemoryItem, User, UserPersonalization } from "@/lib/types";

const DEFAULT_PERSONALIZATION: UserPersonalization = {
  name: "",
  preferred_name: "",
  role: "",
  memories: [],
  use_memories: true,
  enable_memory_tool: true,
  user_preferences: "",
};

function derivePersonalizationFromUser(user: User | null): UserPersonalization {
  if (!user?.personalization) {
    return { ...DEFAULT_PERSONALIZATION, memories: [] };
  }

  return {
    name: user.personalization.name ?? "",
    preferred_name: user.personalization.preferred_name ?? "",
    role: user.personalization.role ?? "",
    memories: [...(user.personalization.memories ?? [])],
    use_memories:
      user.personalization.use_memories ?? DEFAULT_PERSONALIZATION.use_memories,
    enable_memory_tool:
      user.personalization.enable_memory_tool ??
      DEFAULT_PERSONALIZATION.enable_memory_tool,
    user_preferences: user.personalization.user_preferences ?? "",
  };
}

interface UseUserPersonalizationOptions {
  onSuccess?: (saved: Partial<UserPersonalization>) => void;
  onError?: (error: unknown) => void;
}

/**
 * Hook for managing user personalization settings
 *
 * Handles user personalization data including name, role, and memories.
 * Provides state management and persistence for personalization fields with
 * optimistic updates and error handling.
 *
 * @param user - The current user object containing personalization data
 * @param persistPersonalization - Async function to persist a personalization patch to the server
 * @param options - Optional callbacks for success and error handling
 * @param options.onSuccess - Callback invoked when personalization is successfully saved
 * @param options.onError - Callback invoked when personalization save fails
 * @returns Object containing personalization state and handler functions
 *
 * @example
 * ```tsx
 * import useUserPersonalization from "@/hooks/useUserPersonalization";
 * import { useUser } from "@/providers/UserProvider";
 *
 * function ExampleForm() {
 *   const { user, updateUserPersonalization } = useUser();
 *   const {
 *     personalizationValues,
 *     updatePersonalizationField,
 *     toggleUseMemories,
 *     updateMemoryAtIndex,
 *     addMemory,
 *     handleSavePersonalization,
 *     isSavingPersonalization
 *   } = useUserPersonalization(user, updateUserPersonalization, {
 *     onSuccess: () => console.log("Saved!"),
 *     onError: () => console.log("Failed!")
 *   });
 *
 *   return (
 *     <div>
 *       <input
 *         value={personalizationValues.name}
 *         onChange={(e) => updatePersonalizationField("name", e.target.value)}
 *       />
 *       <button
 *         onClick={() =>
 *           handleSavePersonalization({ name: personalizationValues.name })
 *         }
 *         disabled={isSavingPersonalization}
 *       >
 *         Save
 *       </button>
 *     </div>
 *   );
 * }
 * ```
 *
 * @remarks
 * - Changes are optimistic - UI updates immediately before server persistence
 * - On error, state reverts to the last known good value from the user object
 * - A save sends only the fields it is given
 * - Memories are automatically trimmed and filtered (empty strings removed) on save
 * - The hook synchronizes with user prop changes to stay in sync with external updates
 */
export default function useUserPersonalization(
  user: User | null,
  persistPersonalization: (
    patch: Partial<UserPersonalization>
  ) => Promise<void>,
  options?: UseUserPersonalizationOptions
) {
  const [personalizationValues, setPersonalizationValues] =
    useState<UserPersonalization>(() => derivePersonalizationFromUser(user));
  const [isSavingPersonalization, setIsSavingPersonalization] = useState(false);

  const onSuccess = options?.onSuccess;
  const onError = options?.onError;

  const basePersonalization = useMemo(
    () => derivePersonalizationFromUser(user),
    [user]
  );

  useEffect(() => {
    setPersonalizationValues(basePersonalization);
  }, [basePersonalization]);

  const updatePersonalizationField = useCallback(
    (field: "name" | "preferred_name" | "role", value: string) => {
      setPersonalizationValues((prev) => ({
        ...prev,
        [field]: value,
      }));
    },
    []
  );

  const toggleUseMemories = useCallback((useMemories: boolean) => {
    setPersonalizationValues((prev) => ({
      ...prev,
      use_memories: useMemories,
    }));
  }, []);

  const toggleEnableMemoryTool = useCallback((enabled: boolean) => {
    setPersonalizationValues((prev) => ({
      ...prev,
      enable_memory_tool: enabled,
    }));
  }, []);

  const updateUserPreferences = useCallback((value: string) => {
    setPersonalizationValues((prev) => ({
      ...prev,
      user_preferences: value,
    }));
  }, []);

  const updateMemoryAtIndex = useCallback((index: number, value: string) => {
    setPersonalizationValues((prev) => {
      const updatedMemories = [...prev.memories];
      const existing = updatedMemories[index];
      if (existing) {
        updatedMemories[index] = { ...existing, content: value };
      }
      return {
        ...prev,
        memories: updatedMemories,
      };
    });
  }, []);

  const addMemory = useCallback(() => {
    setPersonalizationValues((prev) => ({
      ...prev,
      memories: [...prev.memories, { id: null, content: "" }],
    }));
  }, []);

  const setMemories = useCallback((memories: MemoryItem[]) => {
    setPersonalizationValues((prev) => ({
      ...prev,
      memories,
    }));
  }, []);

  // Sends only `patch`, so a save never overwrites fields the caller does not
  // show, e.g. memories the memory tool added in another tab.
  const handleSavePersonalization = useCallback(
    async (patch: Partial<UserPersonalization>, silent?: boolean) => {
      setIsSavingPersonalization(true);

      const patchToSave: Partial<UserPersonalization> = patch.memories
        ? {
            ...patch,
            memories: patch.memories
              .map((memory) => ({ ...memory, content: memory.content.trim() }))
              .filter((memory) => memory.content.length > 0),
          }
        : patch;

      try {
        await persistPersonalization(patchToSave);
        setPersonalizationValues((previous) => ({
          ...previous,
          ...patchToSave,
        }));
        if (!silent) {
          onSuccess?.(patchToSave);
        }
        return patchToSave;
      } catch (error) {
        setPersonalizationValues(basePersonalization);
        if (!silent) {
          onError?.(error);
        }
        return null;
      } finally {
        setIsSavingPersonalization(false);
      }
    },
    [basePersonalization, onError, onSuccess, persistPersonalization]
  );

  return {
    personalizationValues,
    updatePersonalizationField,
    toggleUseMemories,
    toggleEnableMemoryTool,
    updateUserPreferences,
    updateMemoryAtIndex,
    addMemory,
    setMemories,
    handleSavePersonalization,
    isSavingPersonalization,
  };
}
