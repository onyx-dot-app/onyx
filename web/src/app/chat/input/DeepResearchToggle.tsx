import React from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface DeepToggleProps {
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
}

export function DeepResearchToggle({ enabled, setEnabled }: DeepToggleProps) {
  const handleToggle = () => {
    setEnabled(!enabled);
  };

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            className={`ml-auto py-1.5
            rounded-lg
            group
            px-2  inline-flex items-center`}
            onClick={handleToggle}
            role="switch"
            aria-checked={enabled}
          >
            <div
              className={`
                ${
                  enabled
                    ? "border-background-200 group-hover:border-[#000] dark:group-hover:border-neutral-300"
                    : "border-background-200 group-hover:border-[#000] dark:group-hover:border-neutral-300"
                }
                 relative inline-flex h-[16px] w-8 items-center rounded-full transition-colors focus:outline-none border animate transition-all duration-200 border-background-200 group-hover:border-[1px]  `}
            >
              <span
                className={`${
                  enabled
                    ? "bg-agent translate-x-4 scale-75"
                    : "bg-background-600 group-hover:bg-background-950 translate-x-0.5 scale-75"
                }  inline-block h-[12px] w-[12px]  group-hover:scale-90 transform rounded-full transition-transform duration-200 ease-in-out`}
              />
            </div>
            <span
              className={`ml-2 text-sm font-[550] flex items-center ${
                enabled ? "text-agent" : "text-text-dark"
              }`}
            >
              Deep Research
            </span>
          </button>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          width="w-72"
          className="p-4 bg-white rounded-lg shadow-lg border border-background-200 dark:border-neutral-900"
        >
          <div className="flex items-center space-x-2 mb-3">
            <h3 className="text-sm font-semibold text-neutral-900">
              Agent Search
            </h3>
          </div>
          <p className="text-xs text-neutral-600  dark:text-neutral-700 mb-2">
            Use AI agents to break down questions and run deep iterative
            research through promising pathways. Gives more thorough and
            accurate responses but takes slightly longer.
          </p>
          <ul className="text-xs text-text-600 dark:text-neutral-700 list-disc list-inside">
            <li>Improved accuracy of search results</li>
            <li>Less hallucinations</li>
            <li>More comprehensive answers</li>
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
