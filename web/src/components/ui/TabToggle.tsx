import React from "react";
import { cn } from "@/lib/utils";

export interface TabOption {
  id: string;
  label: string;
  icon?: React.ReactNode;
}

interface TabToggleProps {
  options: TabOption[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

export function TabToggle({
  options,
  value,
  onChange,
  className,
}: TabToggleProps) {
  return (
    <div className={cn("flex w-fit border-b border-border", className)}>
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          className={cn(
            "flex items-center justify-center gap-2 px-6 py-2 text-sm font-medium transition-colors",
            "border-b-2 -mb-[2px]",
            value === option.id
              ? "border-primary text-primary font-semibold"
              : "border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-300"
          )}
        >
          {option.icon && (
            <span
              className={cn(
                "flex-shrink-0",
                value === option.id ? "text-primary" : ""
              )}
            >
              {option.icon}
            </span>
          )}
          <span>{option.label}</span>
        </button>
      ))}
    </div>
  );
}
