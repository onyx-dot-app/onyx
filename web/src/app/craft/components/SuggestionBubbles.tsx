"use client";

import { cn } from "@/lib/utils";
import { SuggestionBubble } from "@/app/craft/hooks/useBuildSessionStore";

interface SuggestionBubblesProps {
  suggestions: SuggestionBubble[];
  loading?: boolean;
  onSelect: (text: string) => void;
}

/**
 * Get theme-specific styles for suggestion bubbles
 */
function getThemeStyles(theme: string): string {
  // Match user message styling - same gray background
  switch (theme) {
    case "add":
    case "question":
    default:
      // Same gray as user messages
      return "bg-background-tint-02 hover:bg-background-tint-03";
  }
}

/**
 * Displays follow-up suggestion bubbles after the first assistant message.
 * Styled like user chat messages - stacked vertically and right-aligned.
 * Each bubble is clickable and populates the input bar with the suggestion text.
 */
export default function SuggestionBubbles({
  suggestions,
  loading,
  onSelect,
}: SuggestionBubblesProps) {
  if (loading) {
    return (
      <div className="flex flex-col items-end gap-2">
        {/* Loading skeleton bubbles - right aligned */}
        {[1, 2].map((i) => (
          <div
            key={i}
            className="h-10 w-48 bg-background-neutral-01 rounded-16 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (!suggestions || suggestions.length === 0) return null;

  return (
    <div className="flex flex-col items-end gap-3">
      {suggestions.map((suggestion, idx) => (
        <button
          key={idx}
          onClick={() => onSelect(suggestion.text)}
          className={cn(
            "px-4 py-3 rounded-t-16 rounded-bl-16 text-sm text-left",
            "text-text-03 transition-colors cursor-pointer",
            "max-w-[95%] shadow-01",
            "animate-in fade-in duration-500",
            getThemeStyles(suggestion.theme)
          )}
          style={{
            animationDelay: `${idx * 100}ms`,
            animationFillMode: "both",
          }}
        >
          {suggestion.text}
        </button>
      ))}
    </div>
  );
}
