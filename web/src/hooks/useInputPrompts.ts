import { useState, useEffect } from "react";
import { InputPrompt } from "@/app/chat/interfaces";

/**
 * Fetches input prompts (prompt shortcuts) for the current user.
 *
 * Returns user-created prompt shortcuts that can be used to quickly insert
 * common prompts in chat. Filters out public/system prompts, returning only
 * prompts created by the current user.
 *
 * @returns Object containing:
 *   - inputPrompts: Array of InputPrompt objects (user's shortcuts only)
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Error object if the fetch failed
 *   - refetch: Function to manually reload the prompts
 *
 * @example
 * const { inputPrompts, isLoading, refetch } = useInputPrompts();
 * if (isLoading) return <Spinner />;
 * return <PromptsList prompts={inputPrompts} onUpdate={refetch} />;
 */
export function useInputPrompts() {
  const [inputPrompts, setInputPrompts] = useState<InputPrompt[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchInputPrompts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/input_prompt");
      if (!response.ok) {
        throw new Error("Failed to fetch input prompts");
      }
      const data = await response.json();
      // Filter to only user-created prompts (exclude public/system prompts)
      const userPrompts = data.filter((p: InputPrompt) => !p.is_public);
      setInputPrompts(userPrompts);
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Unknown error"));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void fetchInputPrompts();
  }, []);

  return {
    inputPrompts,
    isLoading,
    error,
    refetch: fetchInputPrompts,
  };
}
