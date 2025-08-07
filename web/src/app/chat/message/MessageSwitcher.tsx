import { Hoverable } from "@/components/Hoverable";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";

interface MessageSwitcherProps {
  currentPage: number;
  totalPages: number;
  handlePrevious: () => void;
  handleNext: () => void;
  disableForStreaming?: boolean;
}

export function MessageSwitcher({
  currentPage,
  totalPages,
  handlePrevious,
  handleNext,
  disableForStreaming,
}: MessageSwitcherProps) {
  return (
    <div className="flex items-center text-sm space-x-0.5">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div>
              <Hoverable
                icon={FiChevronLeft}
                onClick={
                  disableForStreaming
                    ? () => null
                    : currentPage === 1
                      ? undefined
                      : handlePrevious
                }
              />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            {disableForStreaming
              ? "Wait for agent message to complete"
              : "Previous"}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <span className="text-text-darker select-none">
        {currentPage} / {totalPages}
      </span>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger>
            <div>
              <Hoverable
                icon={FiChevronRight}
                onClick={
                  disableForStreaming
                    ? () => null
                    : currentPage === totalPages
                      ? undefined
                      : handleNext
                }
              />
            </div>
          </TooltipTrigger>
          <TooltipContent>
            {disableForStreaming
              ? "Wait for agent message to complete"
              : "Next"}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
