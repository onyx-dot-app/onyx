import { useChatContext } from "@/components/context/ChatContext";
import {
  getDisplayNameForModel,
  LlmOverride,
  useLlmOverride,
} from "@/lib/hooks";
import {
  DefaultDropdownElement,
  StringOrNumberOption,
} from "@/components/Dropdown";

import { Persona } from "@/app/admin/assistants/interfaces";
import { destructureValue, getFinalLLM, structureValue } from "@/lib/llm/utils";
import { useState } from "react";
import { Hoverable } from "@/components/Hoverable";
import { Popover } from "@/components/popover/Popover";
import { IconType } from "react-icons";
import { FiRefreshCw } from "react-icons/fi";

export function RegenerateDropdown({
  options,
  selected,
  onSelect,
  side,
  maxHeight,
  alternate,
  onDropdownVisibleChange,
}: {
  alternate?: string;
  options: StringOrNumberOption[];
  selected: string | null;
  onSelect: (value: string | number | null) => void;
  includeDefault?: boolean;
  side?: "top" | "right" | "bottom" | "left";
  maxHeight?: string;
  onDropdownVisibleChange: (isVisible: boolean) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);

  const toggleDropdownVisible = (isVisible: boolean) => {
    setIsOpen(isVisible);
    onDropdownVisibleChange(isVisible);
  };

  const Dropdown = (
    <div
      className={`
                border 
                border 
                rounded-lg 
                flex 
                flex-col 
                mx-2
                bg-background
                ${maxHeight || "max-h-96"}
                overflow-y-auto 
                overscroll-contain relative`}
    >
      <p
        className="
                sticky 
                top-0 
                flex
                bg-background
                font-bold
                px-3
                text-sm 
                py-1.5 
                "
      >
        Regenerate with
      </p>
      {options.map((option, ind) => {
        const isSelected = option.value === selected;
        return (
          <DefaultDropdownElement
            key={option.value}
            name={getDisplayNameForModel(option.name)}
            description={option.description}
            onSelect={() => onSelect(option.value)}
            isSelected={isSelected}
          />
        );
      })}
    </div>
  );

  return (
    <Popover
      open={isOpen}
      onOpenChange={toggleDropdownVisible}
      content={
        <div onClick={() => toggleDropdownVisible(!isOpen)}>
          {!alternate ? (
            <Hoverable size={16} icon={FiRefreshCw as IconType} />
          ) : (
            <Hoverable
              size={16}
              icon={FiRefreshCw as IconType}
              hoverText={getDisplayNameForModel(alternate)}
            />
          )}
        </div>
      }
      popover={Dropdown}
      align="start"
      side={side}
      sideOffset={5}
      triggerMaxWidth
    />
  );
}

export default function RegenerateOption({
  selectedAssistant,
  regenerate,
  overriddenModel,
  onHoverChange,
  onDropdownVisibleChange,
}: {
  selectedAssistant: Persona;
  regenerate: (modelOverRide: LlmOverride) => Promise<void>;
  overriddenModel?: string;
  onHoverChange: (isHovered: boolean) => void;
  onDropdownVisibleChange: (isVisible: boolean) => void;
}) {
  const { llmProviders } = useChatContext();
  const llmOverrideManager = useLlmOverride(llmProviders);

  const [_, llmName] = getFinalLLM(llmProviders, selectedAssistant, null);

  const llmOptionsByProvider: {
    [provider: string]: { name: string; value: string }[];
  } = {};
  const uniqueModelNames = new Set<string>();

  llmProviders.forEach((llmProvider) => {
    if (!llmOptionsByProvider[llmProvider.provider]) {
      llmOptionsByProvider[llmProvider.provider] = [];
    }

    (llmProvider.display_model_names || llmProvider.model_names).forEach(
      (modelName) => {
        if (!uniqueModelNames.has(modelName)) {
          uniqueModelNames.add(modelName);
          llmOptionsByProvider[llmProvider.provider].push({
            name: modelName,
            value: structureValue(
              llmProvider.name,
              llmProvider.provider,
              modelName
            ),
          });
        }
      }
    );
  });

  const llmOptions = Object.entries(llmOptionsByProvider).flatMap(
    ([provider, options]) => [...options]
  );

  const currentModelName =
    llmOverrideManager?.llmOverride.modelName ||
    (selectedAssistant
      ? selectedAssistant.llm_model_version_override || llmName
      : llmName);

  return (
    <div
      className="group flex items-center relative"
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => onHoverChange(false)}
    >
      <RegenerateDropdown
        onDropdownVisibleChange={onDropdownVisibleChange}
        alternate={overriddenModel}
        options={llmOptions}
        selected={currentModelName}
        onSelect={(value) => {
          const { name, provider, modelName } = destructureValue(
            value as string
          );
          regenerate({
            name: name,
            provider: provider,
            modelName: modelName,
          });
        }}
      />
    </div>
  );
}
