import { Persona } from "../../app/admin/assistants/interfaces";

import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

export default function AssistantBanner({
  recentAssistants,
  liveAssistant,
  allAssistants,
  onAssistantChange,
  mobile = false,
}: {
  mobile?: boolean;
  recentAssistants: Persona[];
  liveAssistant: Persona | undefined;
  allAssistants: Persona[];
  onAssistantChange: (assistant: Persona) => void;
}) {
  return (
    <div className="flex mx-auto mt-2 gap-4 ">
      {recentAssistants
        // First filter out the current assistant
        .filter((assistant) => assistant.id !== liveAssistant?.id)
        // Combine with visible assistants to get up to 4 total
        .concat(
          allAssistants.filter(
            (assistant) =>
              // Exclude current assistant
              assistant.id !== liveAssistant?.id &&
              // Exclude assistants already in recentAssistants
              !recentAssistants.some((recent) => recent.id === assistant.id)
          )
        )
        // Take first 4
        .slice(0, mobile ? 2 : 4)
        .map((assistant) => (
          <TooltipProvider key={assistant.id}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div
                  className={`${
                    mobile ? "w-full" : "w-36 mx-3"
                  } flex py-1.5 scale-[1.] rounded-full border border-border-recent-assistants justify-center items-center gap-x-2 py-1 px-3 hover:bg-background-125 transition-colors cursor-pointer`}
                  onClick={() => onAssistantChange(assistant)}
                >
                  <AssistantIcon
                    disableToolip
                    size="xs"
                    assistant={assistant}
                  />
                  <span className="font-semibold text-text-recent-assistants text-xs truncate max-w-[120px]">
                    {assistant.name}
                  </span>
                </div>
              </TooltipTrigger>
              <TooltipContent backgroundColor="bg-background">
                <AssistantCard assistant={assistant} />
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ))}
    </div>
  );
}

export function AssistantCard({ assistant }: { assistant: Persona }) {
  return (
    <div className="p-6 backdrop-blur-sm rounded-lg max-w-md w-full mx-auto">
      <div className="flex items-center mb-4">
        <div className="mb-auto mt-2">
          <AssistantIcon disableToolip size="small" assistant={assistant} />
        </div>
        <div className="ml-3">
          <h2 className="text-lg font-semibold text-gray-800">
            {assistant.name}
          </h2>
          <p className="text-sm text-gray-600">{assistant.description}</p>
        </div>
      </div>

      {assistant.tools.length > 0 ||
      assistant.llm_relevance_filter ||
      assistant.llm_filter_extraction ? (
        <div className="space-y-4">
          <h3 className="text-base font-medium text-gray-800">Capabilities</h3>
          <ul className="space-y-2">
            {assistant.tools.map((tool, index) => (
              <li
                key={index}
                className="flex items-center text-sm text-gray-700"
              >
                <span className="mr-2 text-gray-500">•</span>
                {tool.display_name}
              </li>
            ))}
            {assistant.llm_relevance_filter && (
              <li className="flex items-center text-sm text-gray-700">
                <span className="mr-2 text-gray-500">•</span>
                Advanced Relevance Filtering
              </li>
            )}
            {assistant.llm_filter_extraction && (
              <li className="flex items-center text-sm text-gray-700">
                <span className="mr-2 text-gray-500">•</span>
                Smart Information Extraction
              </li>
            )}
          </ul>
        </div>
      ) : (
        <p className="text-sm text-gray-600 italic">
          No specific capabilities listed for this assistant.
        </p>
      )}
    </div>
  );
}
