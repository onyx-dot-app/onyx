"use client";

import useSWR from "swr";
import { InputPrompt } from "@/app/chat/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

/**
 * Hook for fetching user-created prompt shortcuts.
 *
 * Retrieves prompt shortcuts that can be used to quickly insert common prompts
 * in chat. Automatically filters out public/system prompts, returning only
 * prompts created by the current user. Uses SWR for caching and automatic
 * revalidation.
 *
 * @returns Object containing:
 *   - promptShortcuts: Array of InputPrompt objects (user's shortcuts only)
 *   - isLoading: Boolean indicating if data is being fetched
 *   - error: Error object if the fetch failed
 *   - refetch: Function to manually reload the prompts
 *
 * @example
 * ```tsx
 * // Basic usage with loading state
 * const MyComponent = () => {
 *   const { promptShortcuts, isLoading, error } = usePromptShortcuts();
 *
 *   if (isLoading) return <Spinner />;
 *   if (error) return <Error />;
 *
 *   return (
 *     <ul>
 *       {promptShortcuts.map(shortcut => (
 *         <li key={shortcut.id}>{shortcut.prompt}</li>
 *       ))}
 *     </ul>
 *   );
 * };
 * ```
 *
 * @example
 * ```tsx
 * // With refetch after creating a new shortcut
 * const ShortcutManager = () => {
 *   const { promptShortcuts, refetch } = usePromptShortcuts();
 *
 *   const handleCreate = async (newShortcut) => {
 *     await createShortcut(newShortcut);
 *     refetch(); // Refresh the list
 *   };
 *
 *   return <ShortcutsList shortcuts={promptShortcuts} onCreate={handleCreate} />;
 * };
 * ```
 *
 * @example
 * ```tsx
 * // Filtering active shortcuts for slash command menu
 * const SlashCommandMenu = ({ searchTerm }) => {
 *   const { promptShortcuts } = usePromptShortcuts();
 *
 *   const activeShortcuts = promptShortcuts.filter(
 *     (shortcut) =>
 *       shortcut.active &&
 *       shortcut.prompt.toLowerCase().startsWith(searchTerm)
 *   );
 *
 *   return <CommandMenu items={activeShortcuts} />;
 * };
 * ```
 */
export default function usePromptShortcuts() {
  const { data, error, isLoading, mutate } = useSWR<InputPrompt[]>(
    "/api/input_prompt",
    errorHandlingFetcher
  );

  // Filter to only user-created prompts (exclude public/system prompts)
  const promptShortcuts = data?.filter((p) => !p.is_public) ?? [];

  return {
    promptShortcuts,
    isLoading,
    error,
    refetch: mutate,
  };
}
