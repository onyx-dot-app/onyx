import React from "react";
import { Input } from "@/components/ui/input";
import { XIcon } from "lucide-react";
import { LoadingSpinner } from "../LoadingSpinner";

interface SearchInputProps {
  searchQuery: string;
  setSearchQuery: (query: string) => void;
  isSearching: boolean;
}

export function SearchInput({
  searchQuery,
  setSearchQuery,
  isSearching,
}: SearchInputProps) {
  return (
    <div className="relative w-full">
      <div className="flex items-center">
        <Input
          removeFocusRing
          className="w-full !focus-visible:ring-offset-0 !focus-visible:ring-none !focus-visible:ring-0 hover:focus-none border-none bg-transparent placeholder:text-neutral-400 focus:border-transparent focus:outline-none focus:ring-0 dark:placeholder:text-neutral-500 dark:text-neutral-200"
          placeholder="Search chats..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {searchQuery &&
          (isSearching ? (
            <div className="absolute right-2 top-1/2 -translate-y-1/2">
              <LoadingSpinner size="small" />
            </div>
          ) : (
            <XIcon
              size={16}
              className="absolute right-2 top-1/2 -translate-y-1/2 cursor-pointer"
              onClick={() => setSearchQuery("")}
            />
          ))}
      </div>
    </div>
  );
}
