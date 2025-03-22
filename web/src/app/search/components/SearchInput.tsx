import React, { useState, KeyboardEvent } from "react";
import { FiSearch, FiX, FiChevronDown } from "react-icons/fi";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SendIcon } from "@/components/icons/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface SearchInputProps {
  initialQuery?: string;
  onSearch: (query: string) => void;
  placeholder?: string;
  hide?: boolean;
}

type ModeType = "search" | "chat" | "agent";

export const SearchInput = ({
  initialQuery = "",
  onSearch,
  placeholder = "Search...",
  hide = false,
}: SearchInputProps) => {
  const [query, setQuery] = useState(initialQuery);
  const [mode, setMode] = useState<ModeType>("search");

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

  const getModeLabel = () => {
    switch (mode) {
      case "search":
        return "Search Fast";
      case "chat":
        return "Chat";
      case "agent":
        return "Agent";
      default:
        return "Search Fast";
    }
  };

  const getPlaceholderText = () => {
    switch (mode) {
      case "search":
        return placeholder;
      case "chat":
        return "Ask anything...";
      case "agent":
        return "Ask a complex question...";
      default:
        return placeholder;
    }
  };

  return (
    <div
      className={`flex items-center w-full max-w-4xl relative ${
        hide && "invisible"
      }`}
    >
      <div className="absolute left-3 text-gray-500">
        <FiSearch size={16} />
      </div>

      <Input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={getPlaceholderText()}
        className="pl-10 pr-20 py-2 h-10 text-base border border-gray-300 rounded-full focus:border-blue-500 focus:ring-1 focus:ring-blue-500 bg-gray-50"
      />

      <div className="absolute right-3 flex items-center space-x-1">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="px-2 h-8 rounded-md text-xs font-normal flex items-center gap-1"
            >
              {getModeLabel()}
              <FiChevronDown size={14} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-64">
            <DropdownMenuItem
              onClick={() => setMode("search")}
              className="py-2 px-3 cursor-pointer"
            >
              <div className="flex flex-col">
                <span className="font-medium">Search Fast</span>
                <span className="text-xs text-gray-500 mt-1">
                  Find documents quickly
                </span>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => setMode("chat")}
              className="py-2 px-3 cursor-pointer"
            >
              <div className="flex flex-col">
                <span className="font-medium">Chat</span>
                <span className="text-xs text-gray-500 mt-1">
                  Get AI answers. Chat with the LLM.
                </span>
              </div>
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => setMode("agent")}
              className="py-2 px-3 cursor-pointer"
            >
              <div className="flex flex-col">
                <span className="font-medium">Agent</span>
                <span className="text-xs text-gray-500 mt-1">
                  Tackle complex queries or hard-to-find documents
                </span>
              </div>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <button
          className={`cursor-pointer h-[22px] w-[22px] rounded-full ${
            query
              ? "bg-neutral-900 dark:bg-neutral-50"
              : "bg-neutral-500 dark:bg-neutral-400"
          }`}
          onClick={handleSearch}
          aria-label={mode === "search" ? "Search" : "Send message"}
        >
          <SendIcon
            size={22}
            className="text-neutral-50 dark:text-neutral-900 p-1 my-auto"
          />
        </button>
      </div>
    </div>
  );
};
