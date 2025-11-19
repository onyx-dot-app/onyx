import { useCallback, useEffect, useMemo, useState } from "react";
import { User, UserPersonalization } from "@/lib/types";

const DEFAULT_PERSONALIZATION: UserPersonalization = {
  name: "",
  role: "",
  memories: [],
  use_memories: true,
};

function derivePersonalizationFromUser(user: User | null): UserPersonalization {
  if (!user?.personalization) {
    return { ...DEFAULT_PERSONALIZATION, memories: [] };
  }

  return {
    name: user.personalization.name ?? "",
    role: user.personalization.role ?? "",
    memories: [...(user.personalization.memories ?? [])],
    use_memories:
      user.personalization.use_memories ?? DEFAULT_PERSONALIZATION.use_memories,
  };
}

interface UseUserPersonalizationOptions {
  onSuccess?: (personalization: UserPersonalization) => void;
  onError?: (error: unknown) => void;
}

export function useUserPersonalization(
  user: User | null,
  persistPersonalization: (
    personalization: UserPersonalization
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
    (field: "name" | "role", value: string) => {
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

  const updateMemoryAtIndex = useCallback((index: number, value: string) => {
    setPersonalizationValues((prev) => {
      const updatedMemories = [...prev.memories];
      updatedMemories[index] = value;
      return {
        ...prev,
        memories: updatedMemories,
      };
    });
  }, []);

  const addMemory = useCallback(() => {
    setPersonalizationValues((prev) => ({
      ...prev,
      memories: [...prev.memories, ""],
    }));
  }, []);

  const handleSavePersonalization = useCallback(async () => {
    setIsSavingPersonalization(true);
    const trimmedMemories = personalizationValues.memories
      .map((memory) => memory.trim())
      .filter((memory) => memory.length > 0);

    const updatedPersonalization: UserPersonalization = {
      ...personalizationValues,
      memories: trimmedMemories,
    };

    try {
      await persistPersonalization(updatedPersonalization);
      setPersonalizationValues(updatedPersonalization);
      onSuccess?.(updatedPersonalization);
      return updatedPersonalization;
    } catch (error) {
      setPersonalizationValues(basePersonalization);
      onError?.(error);
      return null;
    } finally {
      setIsSavingPersonalization(false);
    }
  }, [
    basePersonalization,
    onError,
    onSuccess,
    persistPersonalization,
    personalizationValues,
  ]);

  return {
    personalizationValues,
    updatePersonalizationField,
    toggleUseMemories,
    updateMemoryAtIndex,
    addMemory,
    handleSavePersonalization,
    isSavingPersonalization,
  };
}
