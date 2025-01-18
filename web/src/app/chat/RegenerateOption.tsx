import { useChatContext } from "@/components/context/ChatContext";
import {
  getDisplayNameForModel,
  LlmOverride,
  useLlmOverride,
} from "@/lib/hooks";
import { StringOrNumberOption } from "@/components/Dropdown";

import { Persona } from "@/app/admin/assistants/interfaces";
import { destructureValue, getFinalLLM, structureValue } from "@/lib/llm/utils";
import { useState } from "react";
import { Hoverable } from "@/components/Hoverable";
import { Popover } from "@/components/popover/Popover";
import { IconType } from "react-icons";
import { FiRefreshCw, FiCheck } from "react-icons/fi";

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
    <div className="overflow-y-auto py-2 min-w-fit bg-white dark:bg-gray-800 rounded-md shadow-lg">
      <div className="mb-1 flex items-center justify-between px-4 pt-2">
        <span className="text-sm text-text-500 dark:text-text-400">
          Regenerate with
        </span>
      </div>
      {options.map((option) => (
        <div
          key={option.value}
          role="menuitem"
          className={`flex items-center m-1.5 p-1.5 text-sm cursor-pointer focus-visible:outline-0 group relative hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md my-0 px-3 mx-2 gap-2.5 py-3 !pr-3 ${
            option.value === selected ? "bg-gray-100 dark:bg-gray-700" : ""
          }`}
          onClick={() => onSelect(option.value)}
        >
          <div className="flex grow items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-3">
                <div>{getDisplayNameForModel(option.name)}</div>
              </div>
            </div>
          </div>
          {option.value === selected && (
            <FiCheck className="text-blue-500 dark:text-blue-400" />
          )}
        </div>
      ))}
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
