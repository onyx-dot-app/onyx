import { useRef, useCallback, useEffect, useState } from "react";
import { MemoryItem } from "@/lib/types";

export interface LocalMemory {
  id: number;
  content: string;
  isNew: boolean;
}

export const MAX_MEMORY_LENGTH = 200;
export const MAX_MEMORY_COUNT = 10;

interface UseMemoryManagerArgs {
  memories: MemoryItem[];
  onSaveMemories: (memories: MemoryItem[]) => Promise<boolean>;
  onNotify: (message: string, type: "success" | "error") => void;
}

export function useMemoryManager({
  memories,
  onSaveMemories,
  onNotify,
}: UseMemoryManagerArgs) {
  const [localMemories, setLocalMemories] = useState<LocalMemory[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const initialMemoriesRef = useRef<MemoryItem[]>([]);
  const isSavingRef = useRef(false);

  // Initialize local memories from props
  useEffect(() => {
    const existingMemories: LocalMemory[] = memories.map((mem, index) => ({
      id: mem.id ?? -(index + 1),
      content: mem.content,
      isNew: mem.id === null,
    }));

    setLocalMemories((prev) => {
      const emptyNewItems = prev.filter((m) => m.isNew && !m.content.trim());
      return [...emptyNewItems, ...existingMemories];
    });
    initialMemoriesRef.current = memories;
  }, [memories]);

  const canAddMemory = localMemories.length < MAX_MEMORY_COUNT;

  const handleAddMemory = useCallback((): number | null => {
    if (localMemories.length >= MAX_MEMORY_COUNT) {
      return null;
    }

    const existingEmpty = localMemories.find(
      (m) => m.isNew && !m.content.trim()
    );
    if (existingEmpty) {
      return existingEmpty.id;
    }

    // Save any unsaved new item with content before creating a new one
    const unsavedNewItem = localMemories.find(
      (m) => m.isNew && m.content.trim()
    );
    if (unsavedNewItem && !isSavingRef.current) {
      const newMemories: MemoryItem[] = localMemories
        .filter((m) => m.content.trim())
        .map((m) => ({ id: m.isNew ? null : m.id, content: m.content }));

      const memoriesChanged =
        JSON.stringify(newMemories) !==
        JSON.stringify(initialMemoriesRef.current);

      if (memoriesChanged) {
        isSavingRef.current = true;
        onSaveMemories(newMemories).then((success) => {
          isSavingRef.current = false;
          if (success) {
            initialMemoriesRef.current = newMemories;
            onNotify("Memory saved", "success");
          } else {
            onNotify("Failed to save memory", "error");
          }
        });
      }
    }

    const newId = Date.now();
    setLocalMemories((prev) => [
      { id: newId, content: "", isNew: true },
      ...prev,
    ]);
    return newId;
  }, [localMemories, onSaveMemories, onNotify]);

  const handleUpdateMemory = useCallback((index: number, value: string) => {
    setLocalMemories((prev) =>
      prev.map((memory, i) =>
        i === index ? { ...memory, content: value } : memory
      )
    );
  }, []);

  const handleRemoveMemory = useCallback(
    async (index: number) => {
      const memory = localMemories[index];
      if (!memory) return;

      if (memory.isNew) {
        setLocalMemories((prev) => prev.filter((_, i) => i !== index));
        return;
      }

      const newMemories: MemoryItem[] = localMemories
        .filter((_, i) => i !== index)
        .filter((m) => !m.isNew || m.content.trim())
        .map((m) => ({ id: m.isNew ? null : m.id, content: m.content }));

      const success = await onSaveMemories(newMemories);
      if (success) {
        onNotify("Memory deleted", "success");
      } else {
        onNotify("Failed to delete memory", "error");
      }
    },
    [localMemories, onSaveMemories, onNotify]
  );

  const handleBlurMemory = useCallback(
    async (index: number) => {
      const memory = localMemories[index];
      if (!memory || !memory.content.trim()) return;
      if (isSavingRef.current) return;

      const newMemories: MemoryItem[] = localMemories
        .filter((m) => m.content.trim())
        .map((m) => ({ id: m.isNew ? null : m.id, content: m.content }));

      const memoriesChanged =
        JSON.stringify(newMemories) !==
        JSON.stringify(initialMemoriesRef.current);

      if (!memoriesChanged) return;

      isSavingRef.current = true;
      const success = await onSaveMemories(newMemories);
      isSavingRef.current = false;
      if (success) {
        initialMemoriesRef.current = newMemories;
        onNotify("Memory saved", "success");
      } else {
        onNotify("Failed to save memory", "error");
      }
    },
    [localMemories, onSaveMemories, onNotify]
  );

  const filteredMemories = localMemories
    .map((memory, originalIndex) => ({ memory, originalIndex }))
    .filter(({ memory }) => {
      if (!searchQuery.trim()) return true;
      return memory.content
        .toLowerCase()
        .includes(searchQuery.trim().toLowerCase());
    });

  const totalLineCount = localMemories.filter(
    (m) => m.content.trim() || m.isNew
  ).length;

  return {
    localMemories,
    searchQuery,
    setSearchQuery,
    filteredMemories,
    totalLineCount,
    canAddMemory,
    handleAddMemory,
    handleUpdateMemory,
    handleRemoveMemory,
    handleBlurMemory,
  };
}
