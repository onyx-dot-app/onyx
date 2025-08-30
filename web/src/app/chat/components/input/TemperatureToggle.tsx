import React, { useState, useEffect, useRef } from "react";
import { FiThermometer } from "react-icons/fi";
import { LlmManager } from "@/lib/hooks";
import { modelSupportsTemperature } from "@/lib/llm/utils";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Slider } from "@/components/ui/slider";
import { ChatInputOption } from "./ChatInputOption";
import { IconProps } from "@/components/icons/icons";

interface TemperatureToggleProps {
  llmManager: LlmManager;
  llmProviders: LLMProviderDescriptor[];
}

const TEMPERATURE_PRESETS = [
  { value: 0, label: "Focused", description: "Precise and deterministic" },
  { value: 1, label: "Balanced", description: "Balanced creativity" },
  { value: 2, label: "Creative", description: "Maximum creativity" },
];

export default function TemperatureToggle({
  llmManager,
  llmProviders,
}: TemperatureToggleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [localTemperature, setLocalTemperature] = useState(
    llmManager.temperature ?? 0.5
  );
  const [showLabel, setShowLabel] = useState(false);
  const labelTimerRef = useRef<NodeJS.Timeout | null>(null);
  
  const supportsTemperature = modelSupportsTemperature(
    llmProviders,
    llmManager.currentLlm.modelName,
    llmManager.currentLlm.name
  );

  useEffect(() => {
    setLocalTemperature(llmManager.temperature ?? 0.5);
  }, [llmManager.temperature]);

  useEffect(() => {
    return () => {
      if (labelTimerRef.current) {
        clearTimeout(labelTimerRef.current);
      }
    };
  }, []);

  const handleTemperatureChange = React.useCallback((value: number[]) => {
    const value_0 = value[0];
    if (value_0 !== undefined) {
      setLocalTemperature(value_0);
    }
  }, []);

  const handleTemperatureChangeComplete = React.useCallback(
    (value: number[]) => {
      const value_0 = value[0];
      if (value_0 !== undefined) {
        llmManager.updateTemperature(value_0);
        setShowLabel(true);
        if (labelTimerRef.current) clearTimeout(labelTimerRef.current);
        labelTimerRef.current = setTimeout(() => setShowLabel(false), 2000);
      }
    },
    [llmManager]
  );

  const handlePresetClick = React.useCallback(
    (presetValue: number) => {
      setLocalTemperature(presetValue);
      llmManager.updateTemperature(presetValue);
      setIsOpen(false);
      setShowLabel(true);
      if (labelTimerRef.current) clearTimeout(labelTimerRef.current);
      labelTimerRef.current = setTimeout(() => setShowLabel(false), 2000);
    },
    [llmManager]
  );

  const ThermometerIcon = ({ size = 16, className }: IconProps) => {
    const t = localTemperature;
    let color = "text-gray-500 dark:text-gray-400";
    if (t < 0.3) color = "text-blue-500 dark:text-blue-400";
    else if (t < 0.7) color = "text-gray-500 dark:text-gray-400";
    else if (t < 1.3) color = "text-orange-500 dark:text-orange-400";
    else color = "text-red-500 dark:text-red-400";
    return <FiThermometer size={size} className={`${color} ${className || ""}`} />;
  };

  if (!supportsTemperature) {
    return (
      <div className="opacity-40">
        <ChatInputOption
          Icon={ThermometerIcon}
          tooltipContent={"This model doesn't support temperature setting"}
          flexPriority="stiff"
        />
      </div>
    );
  }

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <button
          className="dark:text-[#fff] text-[#000] focus:outline-none"
          aria-label={`Temperature: ${localTemperature.toFixed(2)}`}
          onClick={(e) => {
            e.preventDefault();
            setIsOpen((prev) => !prev);
          }}
        >
          <ChatInputOption
            Icon={ThermometerIcon}
            tooltipContent={`Temperature: ${localTemperature.toFixed(1)}`}
            flexPriority="stiff"
            minimize
            toggle={false}
            name={showLabel ? `${localTemperature <= 0.5 ? "Focused" : localTemperature <= 1.5 ? "Balanced" : "Creative"} (${localTemperature.toFixed(1)})` : undefined}
            active={showLabel || isOpen}
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="center"
        className="w-64 p-3 bg-background border border-gray-200 dark:border-gray-700 rounded-md shadow-lg"
      >
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-500 dark:text-gray-400">Temperature</span>
            <span className="text-sm text-gray-500 dark:text-gray-400">
              {localTemperature.toFixed(2)}
            </span>
          </div>
          <div className="flex items-start gap-2 text-xs text-gray-500 dark:text-gray-400">
            <FiThermometer className="mt-0.5" size={14} />
            <p>
              Lower values are more focused and deterministic; higher values increase creativity and variation.
            </p>
          </div>
          <div className="relative pb-6">
            <Slider
              value={[localTemperature]}
              onValueChange={handleTemperatureChange}
              onValueCommit={handleTemperatureChangeComplete}
              max={2}
              step={0.01}
              className="w-full"
            />
            <div className="absolute top-4 left-0 right-0 flex justify-between">
              {TEMPERATURE_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  onClick={() => handlePresetClick(preset.value)}
                  className={`text-[11px] tracking-tight px-1 rounded transition-colors ${
                    Math.abs(localTemperature - preset.value) < 0.1
                      ? "text-primary font-medium"
                      : "text-gray-500 dark:text-gray-400 hover:text-primary"
                  }`}
                  style={{
                    position: 'absolute',
                    left: preset.value === 0 ? '0%' : preset.value === 1 ? '50%' : '100%',
                    transform: preset.value === 1 ? 'translateX(-50%)' : preset.value === 2 ? 'translateX(-100%)' : 'none',
                  }}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="absolute bottom-0 left-0 right-0">
              <div className="relative h-2">
                <span className="absolute left-0 top-0 w-px h-2 bg-gray-300 dark:bg-gray-700" />
                <span className="absolute left-1/2 -translate-x-1/2 top-0 w-px h-2 bg-gray-300 dark:bg-gray-700" />
                <span className="absolute right-0 top-0 w-px h-2 bg-gray-300 dark:bg-gray-700" />
              </div>
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}