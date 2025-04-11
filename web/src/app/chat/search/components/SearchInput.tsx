import React, {
  useState,
  KeyboardEvent,
  useRef,
  useEffect,
  useLayoutEffect,
} from "react";
import { FiSearch, FiChevronDown } from "react-icons/fi";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SendIcon } from "@/components/icons/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { useRouter } from "next/navigation";

type ModeType = "search" | "chat" | "agent";

interface SearchModeDropdownProps {
  mode: ModeType;
  setMode: (mode: ModeType) => void;
  query?: string;
  isMiddle?: boolean;
}

export const SearchModeDropdown = ({
  mode,
  setMode,
  query = "",
  isMiddle = false,
}: SearchModeDropdownProps) => {
  const router = useRouter();

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

  const handleModeChange = (newMode: ModeType) => {
    setMode(newMode);

    if (newMode === "chat") {
      // Navigate to chat with the current query
      const params = new URLSearchParams();
      if (query.trim()) {
        params.append("transitionQuery", query);
      }

      // Add a parameter to indicate starting position
      params.append("fromPosition", isMiddle ? "middle" : "top");

      // For an even cleaner transition, directly set the location
      // This avoids any flash or reload effects from router navigation
      router.push(`/chat?${params.toString()}`);
    } else if (newMode === "agent") {
      const params = new URLSearchParams();
      params.append("agentic", "true");
      if (query.trim()) {
        params.append("transitionQuery", query);
      }
      params.append("fromPosition", isMiddle ? "middle" : "top");
      router.push(`/chat?${params.toString()}`);
    } else {
      const params = new URLSearchParams();
      if (query.trim()) {
        params.append("query", query);
      }

      params.append("fromChat", "true");
      router.push(`/chat/search?${params.toString()}`);
    }
  };

  return (
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
          onClick={() => handleModeChange("search")}
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
          onClick={() => handleModeChange("chat")}
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
          onClick={() => handleModeChange("agent")}
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
  );
};

interface SearchInputProps {
  initialQuery?: string;
  onSearch: (query: string) => void;
  placeholder?: string;
  hide?: boolean;
  isMiddle?: boolean;
  isAnimatingFromChatInitial?: boolean;
}

const TRANSITION_DURATION = 1000; // ms

export const SearchInput = ({
  initialQuery = "",
  onSearch,
  placeholder = "Search...",
  hide = false,
  isMiddle = false,
  isAnimatingFromChatInitial = false,
}: SearchInputProps) => {
  const [query, setQuery] = useState(initialQuery);
  const [mode, setMode] = useState<ModeType>("search");
  const router = useRouter();
  const inputContainerRef = useRef<HTMLDivElement>(null);

  // Check if we're coming from chat
  const searchParams =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search)
      : new URLSearchParams();
  const fromChat = searchParams.get("fromChat") === "true";
  const [isAnimatingFromChat, setIsAnimatingFromChat] = useState(
    isAnimatingFromChatInitial
  );

  // Use layout effect for animations that affect layout
  useLayoutEffect(() => {
    if (fromChat && isMiddle) {
      // Add a style to disable all animations temporarily
      const style = document.createElement("style");
      style.innerHTML = "* { transition: none !important; }";
      document.head.appendChild(style);

      // Force a repaint
      document.body.offsetHeight;

      // Remove the style after a small delay
      setTimeout(() => {
        document.head.removeChild(style);

        // Set initial position (from bottom)
        setIsAnimatingFromChat(true);

        // Start animation after a brief delay
        setTimeout(() => {
          setIsAnimatingFromChat(false);
        }, 50);
      }, 10);
    }
  }, [fromChat, isMiddle]);

  // Position class based on animation state
  const getPositionClass = () => {
    if (isAnimatingFromChat) {
      return "translate-y-[85vh]  scale-[0.85] opacity-60";
    }
    return "translate-y-0 scale-100 opacity-100";
  };

  // Detect if the search input is in the middle of the page
  // alert(isAnimatingFromChat);
  const [inMiddlePosition, setInMiddlePosition] = useState(isMiddle);

  useEffect(() => {
    // Update position state based on prop
    setInMiddlePosition(isMiddle);

    // For auto-detection, we could also use this:
    if (inputContainerRef.current && typeof window !== "undefined") {
      const rect = inputContainerRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      // Consider it in the middle if it's roughly in the middle third of the screen
      const isInMiddleThird =
        rect.top > viewportHeight / 3 && rect.top < (viewportHeight * 2) / 3;

      if (isInMiddleThird && !isMiddle) {
        setInMiddlePosition(true);
      }
    }
  }, [isMiddle]);

  const handleSearch = () => {
    if (query.trim()) {
      onSearch(query);
      // After search is performed, it's definitely not in the middle anymore
      setInMiddlePosition(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleSearch();
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
      ref={inputContainerRef}
      className={`flex items-center w-full max-w-4xl relative transition-all duration-1000 ease-[cubic-bezier(0.16,1,0.3,1)] will-change-transform transform ${getPositionClass()} ${
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
        <SearchModeDropdown
          mode={mode}
          setMode={setMode}
          query={query}
          isMiddle={inMiddlePosition}
        />

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
