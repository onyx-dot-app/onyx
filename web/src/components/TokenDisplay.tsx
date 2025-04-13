import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getDisplayNameForModel } from "@/lib/hooks";

interface TokenDisplayProps {
  totalTokens: number;
  maxTokens: number;
  tokenPercentage: number;
  selectedModel: {
    modelName: string;
  };
}

export function TokenDisplay({
  totalTokens,
  maxTokens,
  tokenPercentage,
  selectedModel,
}: TokenDisplayProps) {
  return (
    <div className="flex items-center">
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center space-x-3 bg-neutral-100 dark:bg-neutral-800 rounded-full px-4 py-1.5">
              <div className="hidden sm:block relative w-24 h-2 bg-neutral-200 dark:bg-neutral-700 rounded-full overflow-hidden">
                <div
                  className={` absolute top-0 left-0 h-full rounded-full ${
                    tokenPercentage >= 100
                      ? "bg-yellow-500 dark:bg-yellow-600"
                      : "bg-green-500 dark:bg-green-600"
                  }`}
                  style={{
                    width: `${Math.min(tokenPercentage, 100)}%`,
                  }}
                ></div>
              </div>
              <div className="text-xs text-neutral-600 dark:text-neutral-300 font-medium whitespace-nowrap">
                {totalTokens.toLocaleString()} / {maxTokens.toLocaleString()}{" "}
                LLM tokens
              </div>
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom" className="max-w-sm">
            <p className="text-xs max-w-xs">
              Maximum tokens for default model{" "}
              {getDisplayNameForModel(selectedModel.modelName)}, if exceeded,
              chat will run a search over the documents rather than including
              all of the contents.
            </p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  );
}
