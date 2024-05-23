import { Persona } from "@/app/admin/assistants/interfaces";
import { Bubble } from "@/components/Bubble";
import { useChatContext } from "@/components/context/ChatContext";
import { getFinalLLM } from "@/lib/llm/utils";
import React from "react";
import { FiBookmark, FiImage, FiSearch } from "react-icons/fi";

export function AssistantsTab({
  selectedAssistant,
  onSelect,
}: {
  selectedAssistant: Persona;
  onSelect: (assistant: Persona) => void;
}) {
  const { availablePersonas, llmProviders } = useChatContext();
  const [_, llmName] = getFinalLLM(llmProviders, null);

  return (
    <div className="mb-4">
      <h3 className="text-lg font-semibold">Choose Assistant</h3>
      <div className="mt-3">
        {availablePersonas.map((assistant) => (
          <div
            key={assistant.id}
            className={`
              cursor-pointer 
              p-3 
              border 
              rounded-md 
              mb-3 
              hover:bg-hover-light
              ${selectedAssistant.id === assistant.id ? "border-accent" : "border-border"}
            `}
            onClick={() => onSelect(assistant)}
          >
            <div className="font-bold text-emphasis mb-1">{assistant.name}</div>
            <div className="text-sm text-subtle mb-1">
              {assistant.description}
            </div>
            <div className="mt-2 flex flex-col gap-y-1">
              {assistant.document_sets.length > 0 && (
                <div className="text-xs text-subtle flex flex-wrap gap-1">
                  <p className="my-auto font-medium">Document Sets:</p>
                  {assistant.document_sets.map((set) => (
                    <Bubble key={set.id} isSelected={false}>
                      <div className="flex flex-row gap-0.5">
                        <FiBookmark className="mr-1 my-auto" />
                        {set.name}
                      </div>
                    </Bubble>
                  ))}
                </div>
              )}
              {assistant.tools.length > 0 && (
                <div className="text-xs text-subtle flex flex-wrap gap-1">
                  <p className="my-auto font-medium">Tools:</p>
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
                        <div className="flex flex-row gap-0.5">
                          {toolIcon}
                          {toolName}
                        </div>
                      </Bubble>
                    );
                  })}
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
    </div>
  );
}
