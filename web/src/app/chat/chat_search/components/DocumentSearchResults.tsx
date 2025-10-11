import React, { useState, useEffect, useRef } from "react";
import { QdrantSearchResult } from "../qdrantInterfaces";
import { FileText } from "lucide-react";
import { highlightText } from "../utils/highlightText";

interface DocumentSearchResultsProps {
  results: QdrantSearchResult[];
  isLoading: boolean;
  searchQuery: string;
}

export function DocumentSearchResults({
  results,
  isLoading,
  searchQuery,
}: DocumentSearchResultsProps) {
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);
  const resultRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Reset selection when results change
  useEffect(() => {
    setSelectedIndex(-1);
    resultRefs.current = resultRefs.current.slice(0, results.length);
  }, [results]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (results.length === 0) return;

      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) =>
          prev < results.length - 1 ? prev + 1 : prev
        );
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev > 0 ? prev - 1 : -1));
      } else if (e.key === "Enter" && selectedIndex >= 0) {
        e.preventDefault();
        // Trigger click on selected result
        resultRefs.current[selectedIndex]?.click();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [results.length, selectedIndex]);

  // Scroll selected item into view
  useEffect(() => {
    if (selectedIndex >= 0 && resultRefs.current[selectedIndex]) {
      resultRefs.current[selectedIndex]?.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
      });
    }
  }, [selectedIndex]);

  if (isLoading) {
    return (
      <div className="px-4 py-2">
        <div className="text-sm text-neutral-500 dark:text-neutral-400">
          Searching documents...
        </div>
      </div>
    );
  }

  if (results.length === 0) {
    return null;
  }

  const handleResultClick = (result: QdrantSearchResult) => {
    // TODO: Implement document preview/open functionality
    console.log("Document clicked:", result.document_id);
  };

  return (
    <div className="px-4 py-2">
      <div className="text-xs font-semibold text-neutral-600 dark:text-neutral-400 mb-2 uppercase tracking-wide">
        Documents ({results.length})
      </div>

      <div className="space-y-1">
        {results.map((result, index) => {
          const isSelected = index === selectedIndex;

          return (
            <div
              key={result.document_id}
              ref={(el) => (resultRefs.current[index] = el)}
              onClick={() => handleResultClick(result)}
              className={`group flex items-start gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                isSelected
                  ? "bg-blue-100 dark:bg-blue-900/30 ring-2 ring-blue-500 dark:ring-blue-400"
                  : "hover:bg-neutral-100 dark:hover:bg-neutral-700"
              }`}
              role="button"
              tabIndex={0}
              aria-selected={isSelected}
            >
              <div className="flex-shrink-0 mt-0.5">
                <FileText
                  size={16}
                  className={`${
                    isSelected
                      ? "text-blue-600 dark:text-blue-400"
                      : "text-neutral-500 dark:text-neutral-400"
                  }`}
                />
              </div>

              <div className="flex-1 min-w-0">
                {result.filename && (
                  <div className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">
                    {highlightText(result.filename, searchQuery)}
                  </div>
                )}

                <div className="text-sm text-neutral-600 dark:text-neutral-400 line-clamp-2 mt-1">
                  {highlightText(result.content, searchQuery)}
                </div>

                <div className="flex items-center gap-2 mt-1">
                  {result.source_type && (
                    <span className="text-xs text-neutral-500 dark:text-neutral-500">
                      {result.source_type}
                    </span>
                  )}
                  <span className="text-xs text-neutral-400 dark:text-neutral-600">
                    Score: {result.score.toFixed(3)}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {results.length > 0 && (
        <div className="text-xs text-neutral-400 dark:text-neutral-600 mt-2 px-3">
          Use ↑↓ arrow keys to navigate, Enter to select
        </div>
      )}
    </div>
  );
}
