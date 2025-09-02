import React from "react";

interface DeepResearchToggleProps {
  deepResearchEnabled: boolean;
  toggleDeepResearch: () => void;
}

export function DeepResearchToggle({
  deepResearchEnabled,
  toggleDeepResearch,
}: DeepResearchToggleProps) {
  return (
    <button
      className={`ml-auto py-1.5
        rounded-lg
        group
        inline-flex 
        items-center
        px-2
        transition-all
        duration-300
        ease-in-out
        ${
          deepResearchEnabled
            ? "bg-blue-highlight text-blue-text dark:bg-transparent"
            : "text-input-text hover:text-neutral-900 hover:bg-background-chat-hover dark:hover:text-neutral-50"
        }
      `}
      onClick={toggleDeepResearch}
      role="switch"
      aria-checked={deepResearchEnabled}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path
          d="M8 7.99999L4.44793 5.72667C4.06499 5.48159 3.83333 5.05828 3.83333 4.60364V1.83333H12.1667V4.60364C12.1667 5.05828 11.935 5.48159 11.5521 5.72667L8 7.99999ZM8 7.99999L11.5521 10.2733C11.935 10.5184 12.1667 10.9417 12.1667 11.3963V14.1667H3.83333V11.3963C3.83333 10.9417 4.06499 10.5184 4.44793 10.2733L8 7.99999ZM13.5 14.1667H2.5M13.5 1.83333H2.5"
          stroke="currentColor"
          strokeOpacity="0.8"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span
        className={`text-sm font-medium overflow-hidden transition-all duration-300 ease-in-out ${
          deepResearchEnabled
            ? "max-w-[100px] opacity-100 ml-2"
            : "max-w-0 opacity-0 ml-0"
        }`}
        style={{
          display: "inline-block",
          whiteSpace: "nowrap",
        }}
      >
        Deep Research
      </span>
    </button>
  );
}
