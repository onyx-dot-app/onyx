"use client";

import { useCurrentAgent } from "@/hooks/useAgents";
import { OnSubmitProps } from "@/hooks/useChatController";

export interface SuggestionsProps {
  onSubmit: (props: OnSubmitProps) => void;
}

/**
 * Home-page suggested-prompt grid.
 *
 * Reads the active agent's `starter_messages` (no change to the data
 * flow) and renders them as a 3-up card grid matching the redesigned
 * landing hero. Each starter message becomes one card:
 *
 *   - the optional `name` shows as a small uppercase category label,
 *   - the `message` is the card's primary title and the prompt that
 *     fires onClick.
 *
 * Cards beyond the first three wrap onto a second row on the same
 * grid; this is intentional — the agent author controls how many
 * starter messages exist.
 *
 * Returns null when no starter messages are available, matching the
 * prior component's contract.
 */
export default function Suggestions({ onSubmit }: SuggestionsProps) {
  const currentAgent = useCurrentAgent();

  if (
    !currentAgent ||
    !currentAgent.starter_messages ||
    currentAgent.starter_messages.length === 0
  ) {
    return null;
  }

  const handleSuggestionClick = (suggestion: string) => {
    onSubmit({
      message: suggestion,
      currentMessageFiles: [],
      deepResearch: false,
    });
  };

  return (
    <div className="w-full max-w-[var(--app-page-main-content-width)] font-['Inter',_sans-serif]">
      <div className="flex items-center gap-2 mb-3 px-1">
        <span className="text-[10px] font-semibold text-neutral-400 uppercase tracking-[0.15em]">
          Suggested for you
        </span>
        <span className="flex-1 h-px bg-neutral-100" />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {currentAgent.starter_messages.map(({ message, name }, index) => (
          <button
            key={index}
            type="button"
            onClick={() => handleSuggestionClick(message)}
            className="group/prompt flex flex-col p-4 bg-white border border-neutral-200/80 rounded-2xl hover:border-[#295EFF]/30 hover:shadow-md hover:shadow-black/[0.03] transition-all text-left"
          >
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-[10px] font-semibold text-[#295EFF] uppercase tracking-wider">
                {name?.trim() || "Suggested"}
              </span>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-neutral-300 group-hover/prompt:text-[#295EFF] group-hover/prompt:translate-x-0.5 transition-all"
              >
                <path d="m9 18 6-6-6-6" />
              </svg>
            </div>
            <div className="text-[14px] font-semibold text-neutral-900 leading-snug">
              {message}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
