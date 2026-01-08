"use client";

import { useMemo, useState } from "react";

/**
 * A generic filtering hook that filters an array of items based on a query string.
 *
 * The hook manages its own query state and uses an extractor function to convert
 * each item into a searchable string, then performs a case-insensitive substring
 * match against the query.
 *
 * @template T - The type of items being filtered
 * @param items - The array of items to filter
 * @param extractor - A function that extracts a searchable string from each item
 * @returns An object containing the query, setQuery function, and filtered items
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const tools = [
 *     { name: "File Reader", description: "Read files" },
 *     { name: "Web Search", description: "Search the web" }
 *   ];
 *
 *   const { query, setQuery, filtered } = useFilter(
 *     tools,
 *     (tool) => `${tool.name} ${tool.description}`
 *   );
 *
 *   return (
 *     <>
 *       <input value={query} onChange={(e) => setQuery(e.target.value)} />
 *       {filtered.map(tool => <div key={tool.name}>{tool.name}</div>)}
 *     </>
 *   );
 * }
 * ```
 *
 * @remarks
 * - Returns all items if the query is empty or whitespace-only
 * - Performs case-insensitive matching
 * - Uses substring matching (includes)
 * - The extractor function is included in dependencies to prevent stale closures.
 *   For optimal performance, memoize the extractor with useCallback if it's expensive.
 */
export default function useFilter<T>(
  items: T[],
  extractor: (item: T) => string
) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const trimmedQuery = query.trim();

    // Return all items if query is empty
    if (!trimmedQuery) {
      return items;
    }

    const lowerQuery = trimmedQuery.toLowerCase();

    return items.filter((item) => {
      const searchableText = extractor(item).toLowerCase();
      return searchableText.includes(lowerQuery);
    });
  }, [query, items, extractor]);

  return { query, setQuery, filtered };
}
