import React from "react";
import { FileText } from "lucide-react";
import { QdrantSearchResult } from "../../chat_search/qdrantInterfaces";
import { highlightText } from "../../chat_search/utils/highlightText";
import { cn } from "@/lib/utils";

interface InlineSearchResultsProps {
  results: QdrantSearchResult[];
  searchQuery: string;
  selectedIndex: number;
  onSelectResult: (result: QdrantSearchResult) => void;
}

export function InlineSearchResults({
  results,
  searchQuery,
  selectedIndex,
  onSelectResult,
}: InlineSearchResultsProps) {
  if (results.length === 0) {
    return (
      <div className="text-sm absolute inset-x-0 top-0 w-full transform -translate-y-full">
        <div className="rounded-lg py-2 px-3 bg-background-neutral-01 border border-border-01 shadow-lg mx-2 mt-2">
          <p className="text-text-03 text-sm">
            No documents found for "{searchQuery}"
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="text-sm absolute inset-x-0 top-0 w-full transform -translate-y-full">
      <div className="rounded-lg overflow-y-auto max-h-[300px] py-1.5 bg-background-neutral-01 border border-border-01 shadow-lg mx-2 mt-2 z-10">
        <div className="px-2 py-1 text-xs font-semibold text-text-03 uppercase tracking-wide">
          Documents ({results.length})
        </div>

        {results.map((result, index) => {
          const isSelected = index === selectedIndex;

          return (
            <button
              key={result.document_id}
              className={cn(
                "w-full px-2 py-1.5 flex items-start gap-2 cursor-pointer rounded",
                isSelected && "bg-background-neutral-02",
                "hover:bg-background-neutral-02"
              )}
              onClick={() => onSelectResult(result)}
            >
              <div className="flex-shrink-0 mt-0.5">
                <FileText
                  size={14}
                  className={cn(isSelected ? "text-blue-600" : "text-text-03")}
                />
              </div>

              <div className="flex-1 min-w-0 text-left">
                {result.filename && (
                  <div className="text-xs font-medium text-text-01 truncate">
                    {highlightText(result.filename, searchQuery)}
                  </div>
                )}

                <div className="text-xs text-text-03 line-clamp-2 mt-0.5">
                  {highlightText(result.content, searchQuery)}
                </div>

                <div className="flex items-center gap-2 mt-0.5">
                  {result.source_type && (
                    <span className="text-[10px] text-text-04">
                      {result.source_type}
                    </span>
                  )}
                  <span className="text-[10px] text-text-04">
                    Score: {result.score.toFixed(3)}
                  </span>
                </div>
              </div>
            </button>
          );
        })}

        <div className="px-2 py-1 text-[10px] text-text-04 border-t border-border-01 mt-1">
          Use ↑↓ to navigate, Enter to select, Esc to close
        </div>
      </div>
    </div>
  );
}
