"use client";

import React from "react";
import Tabs from "@/refresh-components/Tabs";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { SvgBubbleText, SvgSearch, SvgSparkle } from "@opal/icons";
import { AppMode } from "@/providers/AppModeProvider";

export interface ModeToggleProps {
  /** Current mode */
  mode: AppMode;
  /** Callback when mode changes */
  onModeChange: (mode: AppMode) => void;
  /** Whether the toggle is disabled */
  disabled?: boolean;
  /** Whether classification is currently in progress (shows loading state) */
  isClassifying?: boolean;
}

/**
 * Toggle component for switching between Chat, Search, and Auto modes.
 *
 * - **Auto**: Uses LLM classification to determine if query is search or chat
 * - **Chat**: Forces chat mode regardless of query
 * - **Search**: Forces search mode regardless of query
 *
 * @example
 * ```tsx
 * const [mode, setMode] = useState<AppMode>("auto");
 *
 * <ModeToggle
 *   mode={mode}
 *   onModeChange={setMode}
 *   isClassifying={isClassifying}
 * />
 * ```
 */
export function ModeToggle({
  mode,
  onModeChange,
  disabled,
  isClassifying,
}: ModeToggleProps) {
  return (
    <div className="w-fit">
      <Tabs
        value={mode}
        onValueChange={(value) => onModeChange(value as AppMode)}
      >
        <Tabs.List>
          <Tabs.Trigger
            value="auto"
            disabled={disabled}
            tooltip="Automatically detect search or chat"
          >
            Auto
          </Tabs.Trigger>
          <Tabs.Trigger
            value="search"
            icon={SvgSearch}
            disabled={disabled}
            tooltip="Force search mode"
          >
            Search
          </Tabs.Trigger>
          <Tabs.Trigger
            value="chat"
            icon={SvgBubbleText}
            disabled={disabled}
            tooltip="Force chat mode"
          >
            Chat
          </Tabs.Trigger>
        </Tabs.List>
      </Tabs>

      {/* Classification loading indicator */}
      {isClassifying && mode === "auto" && (
        <div className="flex items-center gap-2 mt-1">
          <div className="w-3 h-3 border-2 border-accent-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-xs text-text-03">Classifying...</span>
        </div>
      )}
    </div>
  );
}

/**
 * Compact mode toggle dropdown for selecting between Auto, Search, and Chat modes.
 *
 * @example
 * ```tsx
 * <CompactModeToggle
 *   mode={appMode}
 *   onModeChange={setAppMode}
 *   disabled={isLoading}
 * />
 * ```
 */
export function CompactModeToggle({
  mode,
  onModeChange,
  disabled,
}: Omit<ModeToggleProps, "isClassifying">) {
  return (
    <div className="w-32">
      <InputSelect
        value={mode}
        onValueChange={(value) => onModeChange(value as AppMode)}
        disabled={disabled}
      >
        <InputSelect.Trigger placeholder="Select mode" />
        <InputSelect.Content>
          <InputSelect.Item
            value="auto"
            icon={SvgSparkle}
            description="Automatic Search/Chat mode"
          >
            Auto
          </InputSelect.Item>
          <InputSelect.Item
            value="search"
            icon={SvgSearch}
            description="Quick search for documents"
          >
            Search
          </InputSelect.Item>
          <InputSelect.Item
            value="chat"
            icon={SvgBubbleText}
            description="Conversation and research with follow-up questions"
          >
            Chat
          </InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>
    </div>
  );
}
