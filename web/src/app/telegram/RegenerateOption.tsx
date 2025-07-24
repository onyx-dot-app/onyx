import { useChatContext } from "@/components/context/ChatContext";
import {
  getDisplayNameForModel,
  LlmDescriptor,
  useLlmManager,
} from "@/lib/hooks";

import { Persona } from "@/app/admin/assistants/interfaces";
import { destructureValue } from "@/lib/llm/utils";
import { useState } from "react";
import { Hoverable } from "@/components/Hoverable";
import { IconType } from "react-icons";
import { FiRefreshCw } from "react-icons/fi";
import LLMPopover from "./input/LLMPopover";

export default function RegenerateOption({
  selectedAssistant,
  regenerate,
  overriddenModel,
  onDropdownVisibleChange,
}: {
  selectedAssistant: Persona;
  regenerate: (modelOverRide: LlmDescriptor) => Promise<void>;
  overriddenModel?: string;
  onDropdownVisibleChange: (isVisible: boolean) => void;
}) {
  const { llmProviders } = useChatContext();
  const llmManager = useLlmManager(llmProviders);
  const [isOpen, setIsOpen] = useState(false);
  const toggleDropdownVisible = (isVisible: boolean) => {
    setIsOpen(isVisible);
    onDropdownVisibleChange(isVisible);
  };

  return (
    <LLMPopover
      llmManager={llmManager}
      llmProviders={llmProviders}
      requiresImageGeneration={false}
      currentAssistant={selectedAssistant}
      currentModelName={overriddenModel}
      trigger={
        <div onClick={() => toggleDropdownVisible(!isOpen)}>
          {!overriddenModel ? (
            <Hoverable size={16} icon={FiRefreshCw as IconType} />
          ) : (
            <Hoverable
              size={16}
              icon={FiRefreshCw as IconType}
              hoverText={getDisplayNameForModel(overriddenModel)}
            />
          )}
        </div>
      }
      onSelect={(value) => {
        const { name, provider, modelName } = destructureValue(value as string);
        regenerate({
          name: name,
          provider: provider,
          modelName: modelName,
        });
      }}
    />
  );
}
