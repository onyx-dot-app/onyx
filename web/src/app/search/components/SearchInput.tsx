import React, { useState, KeyboardEvent } from "react";
import { FiSearch, FiX } from "react-icons/fi";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface SearchInputProps {
  onSearch: (query: string) => void;
  initialQuery?: string;
  placeholder?: string;
}

export function SearchInput({
  onSearch,
  initialQuery = "",
  placeholder = "Search...",
}: SearchInputProps) {
  const [query, setQuery] = useState(initialQuery);

  const handleSearch = () => {
    if (query.trim()) {
      onSearch(query);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleSearch();
    }
  };

  const clearSearch = () => {
    setQuery("");
  };

  return (
    <div className="flex items-center w-full max-w-4xl relative">
      <div className="absolute left-3 text-gray-400">
        <FiSearch size={16} />
      </div>

      <Input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="pl-10 pr-10 py-2 h-10 text-base border border-gray-300 rounded-full focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-gray-50"
      />

      {query && (
        <div className="absolute right-3 flex items-center">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 rounded-full text-gray-400 hover:text-gray-600 hover:bg-gray-100"
            onClick={clearSearch}
          >
            <FiX size={16} />
          </Button>
        </div>
      )}
    </div>
  );
}
