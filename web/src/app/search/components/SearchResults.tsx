import React from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SearchResultItem } from "./SearchResultItem";

interface SearchResultsProps {
  documents: OnyxDocument[];
  onDocumentClick: (document: OnyxDocument) => void;
  isLoading?: boolean;
}

export function SearchResults({
  documents,
  onDocumentClick,
  isLoading = false,
}: SearchResultsProps) {
  if (isLoading) {
    return (
      <div className="flex flex-col w-full h-full items-center justify-start py-4">
        <div className="animate-pulse w-full flex flex-col  gap-4">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="flex gap-3 p-4">
              <div className="rounded-full bg-background-200 h-8 w-8"></div>
              <div className="flex-1 space-y-3">
                <div className="h-4 bg-background-200 rounded w-3/4"></div>
                <div className="h-3 bg-background-200 rounded w-full"></div>
                <div className="h-3 bg-background-200 rounded w-5/6"></div>
                <div className="h-2 bg-background-200 rounded w-1/4"></div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="flex flex-col w-full h-full items-center justify-center py-8">
        <p className="text-text-500">No results found</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col w-full">
      {documents.map((doc, ind) => (
        <SearchResultItem key={ind} document={doc} onClick={onDocumentClick} />
      ))}
    </div>
  );
}
