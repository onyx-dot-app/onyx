import React from "react";
import { User, Users, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";

// Define a simplified Assistant interface with only the properties we use
interface Assistant {
  id: number;
  name: string;
}

interface SharingPanelProps {
  assistantIds?: number[];
  assistants: Assistant[];
  isOpen: boolean;
  onToggle: () => void;
}

export function SharingPanel({
  assistantIds = [],
  assistants,
  isOpen,
  onToggle,
}: SharingPanelProps) {
  const count = assistantIds.length;
  return (
    <div className="p-4 border-b border-[#d9d9d0]">
      <div
        className="text-[#13343a] dark:text-neutral-300 flex items-center justify-between"
        onClick={onToggle}
      >
        <div className="flex items-center">
          {count > 0 ? (
            <>
              <Users className="w-5 h-4 mr-3 " />
              <span className="text-sm font-medium leading-tight">
                Shared with {count} Assistant{count > 1 ? "s" : ""}
              </span>
            </>
          ) : (
            <>
              <User className="w-5 h-4 mr-3 " />
              <span className="text-sm font-medium leading-tight">
                Not shared
              </span>
            </>
          )}
        </div>
        <Button variant="ghost" size="sm" className="w-6 h-6 p-0 rounded-full">
          {isOpen ? (
            <ChevronDown className="w-[15px] h-3 " />
          ) : (
            <ChevronRight className="w-[15px] h-3 " />
          )}
        </Button>
      </div>
      {isOpen && (
        <div className="mt-2 text-[#64645e] dark:tex-neutral-300 text-sm font-normal leading-tight">
          {count > 0 ? (
            <div className="flex flex-wrap gap-2 mt-1">
              {assistantIds.map((id) => {
                const assistant = assistants.find((a) => a.id === id);
                return assistant ? (
                  <a
                    href={`/assistants/edit/${assistant.id}`}
                    key={assistant.id}
                    className="flex bg-neutral-200/80 hover:bg-neutral-200 dark:bg-neutral-700/80 dark:hover:bg-neutral-700 cursor-pointer px-2 py-1 rounded-md items-center space-x-2"
                  >
                    <AssistantIcon assistant={assistant as any} size="xs" />
                    <span className="text-sm font-medium text-gray-700 dark:text-neutral-300">
                      {assistant.name}
                    </span>
                  </a>
                ) : null;
              })}
            </div>
          ) : (
            <span>Not shared with any assistants</span>
          )}
        </div>
      )}
    </div>
  );
}
