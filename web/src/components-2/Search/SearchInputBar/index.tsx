import { SearchIcon, EditIcon } from "@/components/icons/icons";
import { Separator } from "@/components/ui/separator";
import React, { useState } from "react";
import { FiX } from "react-icons/fi";

type SearchInputBarProps = {
  onSubmit?: () => void;
  value: string | null;
  onChange?: (text: string | null) => void;
  onClear?: () => void;
};

export default function SearchInputBar({
  onSubmit,
  value,
  onChange,
  onClear,
}: SearchInputBarProps) {
  return (
    <div className="relative w-full">
      <input
        value={value || ""}
        onChange={(event) => onChange?.(event.target.value)}
        className="
          px-6
          w-full
          h-fit
          py-4
          flex
          flex-col
          shadow-lg
          bg-input-background
          dark:border-none
          rounded-2xl
          overflow-hidden
          text-text-chatbar
          focus:outline-none
          border-[0.5px]
          h-[60px]
          rounded-2xl
          pr-12
        "
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !(event.nativeEvent as any).isComposing
          ) {
            event.preventDefault();
            onSubmit?.();
          }
        }}
      />

      {!value && (
        <div className="absolute inset-y-0 px-6 flex items-center pointer-events-none">
          <span className="text-sm text-neutral-400">Search Anything</span>
        </div>
      )}

      <div className="absolute inset-y-0 right-0 px-6 flex items-center flex gap-x-6">
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onClear?.();
          }}
          className={`
            text-neutral-400
            hover:text-neutral-700
            dark:text-neutral-500
            dark:hover:text-neutral-300
            ease-in-out
            transition-all
            duration-200
            ${value ? "opacity-100" : "opacity-0"}
          `}
        >
          <FiX size={18} />
        </button>
        <Separator
          orientation="vertical"
          className={`h-[50%] bg-neutral-300 transition-all duration-200 ease-in-out ${
            value ? "opacity-100" : "opacity-0"
          }`}
        />
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onSubmit?.();
          }}
          className={`
            text-neutral-400
            hover:text-neutral-700
            dark:text-neutral-500
            dark:hover:text-neutral-300
            ease-in-out
            transition-all
            duration-200
          `}
        >
          <SearchIcon size={18} />
        </button>
      </div>
    </div>
  );
}
