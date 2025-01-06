import { useChatContext } from "@/components/context/ChatContext";
import { LlmOverrideManager } from "@/lib/hooks";
import React, { forwardRef, useCallback, useState } from "react";
import { debounce } from "lodash";
import Text from "@/components/ui/text";
import { Persona } from "@/app/admin/assistants/interfaces";
import { destructureValue } from "@/lib/llm/utils";
import { updateModelOverrideForChatSession } from "../../lib";
import { GearIcon } from "@/components/icons/icons";
import { LlmList } from "@/components/llm/LLMList";
import { checkPersonaRequiresImageGeneration } from "@/app/admin/assistants/lib";

interface LlmTabProps {
  llmOverrideManager: LlmOverrideManager;
  currentLlm: string;
  openModelSettings: () => void;
  chatSessionId?: string;
  close: () => void;
  currentAssistant: Persona;
}

export const LlmTab = forwardRef<HTMLDivElement, LlmTabProps>(
  (
    {
      llmOverrideManager,
      chatSessionId,
      currentLlm,
      close,
      openModelSettings,
      currentAssistant,
    },
    ref
  ) => {
    const requiresImageGeneration =
      checkPersonaRequiresImageGeneration(currentAssistant);

    const { llmProviders } = useChatContext();
    const { updateLLMOverride, temperature, updateTemperature } =
      llmOverrideManager;
    const [isTemperatureExpanded, setIsTemperatureExpanded] = useState(false);

    return (
      <div className="w-full">
        <div className="flex w-full justify-between content-center mb-2 gap-x-2">
          <label className="block text-sm font-medium">Choose Model</label>
          <button
            onClick={() => {
              close();
              openModelSettings();
            }}
          >
            <GearIcon />
          </button>
        </div>
        <LlmList
          requiresImageGeneration={requiresImageGeneration}
          llmProviders={llmProviders}
          currentLlm={currentLlm}
          onSelect={(value: string | null) => {
            if (value == null) {
              return;
            }
            updateLLMOverride(destructureValue(value));
            if (chatSessionId) {
              updateModelOverrideForChatSession(chatSessionId, value as string);
            }
            close();
          }}
        />

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
                    updateTemperature(parseFloat(e.target.value))
                  }
                  className="w-full p-2 border border-border rounded-md"
                  min="0"
                  max="2"
                  step="0.01"
                  value={temperature || 0}
                />
                <div
                  className="absolute text-sm"
                  style={{
                    left: `${(temperature || 0) * 50}%`,
                    transform: `translateX(-${Math.min(
                      Math.max((temperature || 0) * 50, 10),
                      90
                    )}%)`,
                    top: "-1.5rem",
                  }}
                >
                  {temperature}
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
