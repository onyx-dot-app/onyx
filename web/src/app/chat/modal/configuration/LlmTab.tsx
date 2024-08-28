import { useChatContext } from "@/components/context/ChatContext";
import { getDisplayNameForModel, LlmOverrideManager } from "@/lib/hooks";
import React, { forwardRef, useCallback, useRef, useState } from "react";
import { debounce } from "lodash";
import { DefaultDropdown } from "@/components/Dropdown";
import { Text } from "@tremor/react";
import { Persona } from "@/app/admin/assistants/interfaces";
import { destructureValue, getFinalLLM, structureValue } from "@/lib/llm/utils";
import { updateModelOverrideForChatSession } from "../../lib";
import { Tooltip } from "@/components/tooltip/Tooltip";
import { GearIcon, InfoIcon } from "@/components/icons/icons";
import { CustomTooltip } from "@/components/tooltip/CustomTooltip";

interface LlmTabProps {
  llmOverrideManager: LlmOverrideManager;
  currentAssistant: Persona;
  currentLlm: string;
  openModelSettings: () => void;
  chatSessionId?: number;
  close: () => void;
}

export const LlmTab = forwardRef<HTMLDivElement, LlmTabProps>(
  (
    {
      llmOverrideManager,
      currentAssistant,
      chatSessionId,
      currentLlm,
      close,
      openModelSettings,
    },
    ref
  ) => {
    const { llmProviders } = useChatContext();
    const { setLlmOverride, temperature, setTemperature } = llmOverrideManager;
    const [isTemperatureExpanded, setIsTemperatureExpanded] = useState(false);
    const [localTemperature, setLocalTemperature] = useState<number>(
      temperature || 0
    );

    const debouncedSetTemperature = useCallback(
      debounce((value) => {
        setTemperature(value);
      }, 300),
      []
    );

    const handleTemperatureChange = (value: number) => {
      setLocalTemperature(value);
      debouncedSetTemperature(value);
    };

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
    return (
      <div className="w-full">
        <div className="flex w-full justify-between content-center mb-2 gap-x-2">
          <label className="block text-sm font-medium ">Choose Model</label>
          <button
            onClick={() => {
              close();
              openModelSettings();
            }}
          >
            <GearIcon />
          </button>
        </div>
        <div className="max-h-[300px] flex flex-col gap-y-1 overflow-y-scroll">
          {llmOptions.map(({ name, value }, index) => {
            return (
              <button
                key={index}
                className={`w-full py-1.5 px-2 text-sm ${currentLlm == name ? "bg-background-200" : "bg-background-100/50 hover:bg-background-100"} text-left rounded`}
                onClick={() => {
                  setLlmOverride(destructureValue(value));
                  if (chatSessionId) {
                    updateModelOverrideForChatSession(
                      chatSessionId,
                      value as string
                    );
                  }
                  close();
                }}
              >
                {getDisplayNameForModel(name)}
              </button>
            );
          })}
        </div>
        <div className="mt-4">
          <button
            className="flex items-center text-sm font-medium transition-colors duration-200"
            onClick={() => setIsTemperatureExpanded(!isTemperatureExpanded)}
          >
            <span className="mr-2 text-xs text-primary">
              {isTemperatureExpanded ? "▼" : "►"}
            </span>
            <span>Temperature</span>
          </button>

          {isTemperatureExpanded && (
            <>
              <Text className="mt-2 mb-8">
                Adjust the temperature of the LLM. Higher temperatures will make
                the LLM generate more creative and diverse responses, while
                lower temperature will make the LLM generate more conservative
                and focused responses.
              </Text>

              <div className="relative w-full">
                <input
                  type="range"
                  onChange={(e) =>
                    handleTemperatureChange(parseFloat(e.target.value))
                  }
                  className="w-full p-2 border border-border rounded-md"
                  min="0"
                  max="2"
                  step="0.01"
                  value={localTemperature}
                />
                <div
                  className="absolute text-sm"
                  style={{
                    left: `${(localTemperature || 0) * 50}%`,
                    transform: `translateX(-${Math.min(
                      Math.max((localTemperature || 0) * 50, 10),
                      90
                    )}%)`,
                    top: "-1.5rem",
                  }}
                >
                  {localTemperature}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }
);
LlmTab.displayName = "LlmTab";
