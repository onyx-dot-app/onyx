import { Persona } from "@/app/admin/assistants/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/models/llm/interfaces";
import { Bubble } from "@/components/Bubble";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { getFinalLLM } from "@/lib/llm/utils";
import React from "react";
import { FiBookmark, FiImage, FiSearch } from "react-icons/fi";

interface AssistantsTabProps {
  selectedAssistant: Persona;
  availableAssistants: Persona[];
  llmProviders: LLMProviderDescriptor[];
  onSelect: (assistant: Persona) => void;
}

export function AssistantsTab({
  selectedAssistant,
  availableAssistants,
  llmProviders,
  onSelect,
}: AssistantsTabProps) {
  const [_, llmName] = getFinalLLM(llmProviders, null, null);

  return (
    <>
      <h3 className="text-lg font-semibold">Choose Assistant</h3>
      <div className="my-3 grid grid-cols-1 gap-4">
        {availableAssistants.map((assistant) => (
          <div
            key={assistant.id}
            className={`
              cursor-pointer 
              p-4 
              border 
              rounded-lg 
              shadow-md 
              hover:bg-hover-light
              ${
                selectedAssistant.id === assistant.id
                  ? "border-accent"
                  : "border-border"
              }
            `}
            onClick={() => onSelect(assistant)}
          >
            <div className="flex items-center mb-2">
              <AssistantIcon assistant={assistant} />
              <div className="ml-2 font-bold text-lg text-emphasis">
                {assistant.name}
              </div>
            </div>
            {assistant.tools.length > 0 && (
              <div className="text-xs text-subtle flex flex-wrap gap-2">
                {assistant.tools.map((tool) => {
                  let toolName = tool.name;
                  let toolIcon = null;

                  if (tool.name === "SearchTool") {
                    toolName = "Search";
                    toolIcon = <FiSearch className="mr-1 my-auto" />;
                  } else if (tool.name === "ImageGenerationTool") {
                    toolName = "Image Generation";
                    toolIcon = <FiImage className="mr-1 my-auto" />;
                  }

                  return (
                    <Bubble key={tool.id} isSelected={false}>
                      <div className="flex flex-row gap-1">
                        {toolIcon}
                        {toolName}
                      </div>
                    </Bubble>
                  );
                })}
              </div>
            )}
            <div className="text-sm text-subtle mb-2 mt-2">
              {assistant.description}
            </div>
            <div className="mt-2 flex flex-col gap-y-2">
              {assistant.document_sets.length > 0 && (
                <div className="text-xs text-subtle flex flex-wrap gap-2">
                  <p className="my-auto font-medium">Document Sets:</p>
                  {assistant.document_sets.map((set) => (
                    <Bubble key={set.id} isSelected={false}>
                      <div className="flex flex-row gap-1">
                        <FiBookmark className="mr-1 my-auto" />
                        {set.name}
                      </div>
                    </Bubble>
                  ))}
                </div>
              )}
              <div className="text-xs text-subtle">
                <span className="font-medium">Default Model:</span>{" "}
                <i>{assistant.llm_model_version_override || llmName}</i>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
