import React from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SearchIcon } from "lucide-react";

interface AgenticToggleProps {
  proSearchEnabled: boolean;
  setProSearchEnabled: (enabled: boolean) => void;
}

const ProSearchIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    <path
      d="M21 21L16.65 16.65M19 11C19 15.4183 15.4183 19 11 19C6.58172 19 3 15.4183 3 11C3 6.58172 6.58172 3 11 3C15.4183 3 19 6.58172 19 11Z"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M11 8V14M8 11H14"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export function AgenticToggle({
  proSearchEnabled,
  setProSearchEnabled,
}: AgenticToggleProps) {
  const handleToggle = () => {
    setProSearchEnabled(!proSearchEnabled);
  };

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            className={`ml-auto py-1.5
            hover:bg-background-chat-hover
            rounded-lg
            group
            px-2  inline-flex items-center`}
            onClick={handleToggle}
            role="switch"
            aria-checked={proSearchEnabled}
          >
            <div
              className={`
                ${proSearchEnabled ? "border-text" : "border-[#D9D9D0]"}
                 relative inline-flex h-[22px] w-10 items-center rounded-full transition-colors focus:outline-none border animate transition-all duration-200 border-[#D9D9D0] group-hover:border-[1px] group-hover:border-black `}
            >
              <span
                className={`${
                  proSearchEnabled
                    ? "bg-text translate-x-5"
                    : "bg-[#64645E] translate-x-0.5"
                } group-hover:bg-text inline-block h-[18px] w-[18px] scale-75 group-hover:scale-90 transform rounded-full transition-transform duration-200 ease-in-out`}
              />
            </div>
            <span
              className={`ml-2 text-sm font-normal flex items-center ${
                proSearchEnabled ? "text-text" : "text-text-dark"
              }`}
            >
              Pro
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="w-72 p-4 bg-white rounded-lg shadow-lg border border-gray-200"
        >
          <div className="flex items-center space-x-2 mb-3">
            <h3 className="text-sm font-semibold text-gray-900">Pro Search</h3>
          </div>
          <p className="text-xs text-gray-600 mb-2">
            Pro Search uses advanced AI to improve search results, making them
            more accurate and relevant to your needs.
          </p>
          <ul className="text-xs text-gray-600 list-disc list-inside">
            <li>Better understanding of complex queries</li>
            <li>Connects information across multiple documents</li>
            <li>Improves over time based on usage</li>
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
