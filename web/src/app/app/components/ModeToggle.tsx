"use client";

import React from "react";
import Tabs from "@/refresh-components/Tabs";
import { SvgBubbleText, SvgSearch } from "@opal/icons";

export type AppMode = "chat" | "search" | "auto";

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
 * Compact mode toggle for use in tight spaces (e.g., input bar)
 */
export function CompactModeToggle({
  mode,
  onModeChange,
  disabled,
}: Omit<ModeToggleProps, "isClassifying">) {
  return (
    <div className="flex items-center gap-1 bg-background-tint-03 rounded-full p-0.5">
      <button
        type="button"
        onClick={() => onModeChange("auto")}
        disabled={disabled}
        className={`
          px-2 py-1 text-xs rounded-full transition-colors
          ${
            mode === "auto"
              ? "bg-background-neutral-00 text-text-04 shadow-01"
              : "text-text-03 hover:text-text-04"
          }
          ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
        `}
        title="Auto-detect mode"
      >
        Auto
      </button>
      <button
        type="button"
        onClick={() => onModeChange("search")}
        disabled={disabled}
        className={`
          px-2 py-1 text-xs rounded-full transition-colors flex items-center gap-1
          ${
            mode === "search"
              ? "bg-background-neutral-00 text-text-04 shadow-01"
              : "text-text-03 hover:text-text-04"
          }
          ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
        `}
        title="Search mode"
      >
        <SvgSearch size={12} />
      </button>
      <button
        type="button"
        onClick={() => onModeChange("chat")}
        disabled={disabled}
        className={`
          px-2 py-1 text-xs rounded-full transition-colors flex items-center gap-1
          ${
            mode === "chat"
              ? "bg-background-neutral-00 text-text-04 shadow-01"
              : "text-text-03 hover:text-text-04"
          }
          ${disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
        `}
        title="Chat mode"
      >
        <SvgBubbleText size={12} />
      </button>
    </div>
  );
}
