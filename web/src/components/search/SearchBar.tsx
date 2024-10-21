import React, { KeyboardEvent, ChangeEvent, useContext } from "react";

import { MagnifyingGlass } from "@phosphor-icons/react";
interface FullSearchBarProps {
  disabled: boolean;
  query: string;
  setQuery: (query: string) => void;
  onSearch: (fast?: boolean) => void;
  agentic?: boolean;
  toggleAgentic?: () => void;
  ccPairs: CCPairBasicInfo[];
  documentSets: DocumentSet[];
  filterManager: any; // You might want to replace 'any' with a more specific type
  finalAvailableDocumentSets: DocumentSet[];
  finalAvailableSources: string[];
  tags: Tag[];
}

import { useRef } from "react";
import { SendIcon } from "../icons/icons";
import { Divider } from "@tremor/react";
import { CustomTooltip } from "../tooltip/CustomTooltip";
import KeyboardSymbol from "@/lib/browserUtilities";
import { HorizontalSourceSelector } from "./filtering/Filters";
import { CCPairBasicInfo, DocumentSet, Tag } from "@/lib/types";
import { Input } from "@/components/ui/input";

export const AnimatedToggle = ({
  isOn,
  handleToggle,
}: {
  isOn: boolean;
  handleToggle: () => void;
}) => {
  const commandSymbol = KeyboardSymbol();
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  return (
    <CustomTooltip
      light
      large
      content={
        <div className="bg-white my-auto p-6 rounded-lg w-full">
          <h2 className="text-xl text-text-800 font-bold mb-2">
            Agentic Search
          </h2>
          <p className="text-text-700 text-sm mb-4">
            Our most powerful search, have an AI agent guide you to pinpoint
            exactly what you&apos;re looking for.
          </p>
          <Divider />
          <h2 className="text-xl text-text-800 font-bold mb-2">Fast Search</h2>
          <p className="text-text-700 text-sm mb-4">
            Get quality results immediately, best suited for instant access to
            your documents.
          </p>
          <p className="mt-2 flex text-xs">Shortcut: ({commandSymbol}/)</p>
        </div>
      }
    >
      <div
        ref={containerRef}
        className="my-auto ml-auto flex justify-end items-center cursor-pointer"
        onClick={handleToggle}
      >
        <div ref={contentRef} className="flex items-center">
          {/* Toggle switch */}
          <div
            className={`
            w-10 h-6 flex items-center rounded-full p-1 transition-all duration-300 ease-in-out
            ${isOn ? "bg-background-400" : "bg-background-200"}
          `}
          >
            <div
              className={`
              bg-white w-4 h-4 rounded-full shadow-md transform transition-all duration-300 ease-in-out
              ${isOn ? "translate-x-4" : ""}
            `}
            ></div>
          </div>
          <p className="ml-2 text-sm">Agentic</p>
        </div>
      </div>
    </CustomTooltip>
  );
};

export default AnimatedToggle;

export const FullSearchBar = ({
  disabled,
  query,
  setQuery,
  onSearch,
  agentic,
  toggleAgentic,
  ccPairs,
  documentSets,
  filterManager,
  finalAvailableDocumentSets,
  finalAvailableSources,
  tags,
}: FullSearchBarProps) => {
  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    const target = event.target;
    setQuery(target.value);

    // Resize the textarea to fit the content
    target.style.height = "24px";
    const newHeight = target.scrollHeight;
    target.style.height = `${newHeight}px`;
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !(event.nativeEvent as any).isComposing
    ) {
      event.preventDefault();
      if (!disabled) {
        onSearch(agentic);
      }
    }
  };

  return (
    <div
      className="
        opacity-100
        w-full
        h-fit
        flex
        flex-col
        border
        border-border-medium
        rounded-lg
        bg-background-chatbar
        [&:has(textarea:focus)]::ring-1
        [&:has(textarea:focus)]::ring-black
        text-text-chatbar
        "
    >
      <textarea
        rows={3}
        onKeyDownCapture={handleKeyDown}
        className={`
          m-0
          w-full
          shrink
          resize-none
          border-0
          bg-background-chatbar
          whitespace-normal
          rounded-lg
          break-word
          overscroll-contain
          outline-none
          placeholder-subtle
          pl-4
          pr-12
          max-h-[6em]
          py-4
          h-14
          placeholder:text-text-chatbar-subtle
        `}
        autoFocus
        style={{ scrollbarWidth: "thin" }}
        role="textarea"
        aria-multiline
        placeholder="Search for anything..."
        value={query}
        onChange={handleChange}
        onKeyDown={(event) => {}}
        suppressContentEditableWarning={true}
      />
      <div
        className={`flex flex-nowrap overflow-y-hidden "2xl:justify-end" justify-between 4xl:justify-end w-full max-w-full items-center space-x-3 py-3 px-4`}
      >
        <div className="flex-shrink-0 flex items-center my-auto gap-x-3">
          {toggleAgentic && (
            <AnimatedToggle isOn={agentic!} handleToggle={toggleAgentic} />
          )}
          <div className="my-auto pl-2">
            <button
              disabled={disabled}
              onClick={() => {
                onSearch(agentic);
              }}
              className="flex my-auto cursor-pointer"
            >
              <SendIcon
                size={28}
                className={`text-emphasis ${disabled || !query ? "bg-disabled-submit-background" : "bg-submit-background"} text-white p-1 rounded-full`}
              />
            </button>
          </div>
        </div>
      </div>
      <div className="absolute bottom-2.5 right-10"></div>
    </div>
  );
};

interface SearchBarProps {
  query: string;
  setQuery: (query: string) => void;
  onSearch: () => void;
}

export const SearchBar = ({ query, setQuery, onSearch }: SearchBarProps) => {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const target = event.target;
    setQuery(target.value);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !(event.nativeEvent as any).isComposing
    ) {
      onSearch();
      event.preventDefault();
    }
  };

  return (
    <div className="relative w-full">
      <MagnifyingGlass
        size={16}
        className=" absolute left-2 top-1/2 -translate-y-1/2"
      />
      <Input
        autoFocus
        aria-multiline
        placeholder="Search..."
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        suppressContentEditableWarning={true}
        className="pl-7 placeholder:text-subtle"
      />
    </div>
  );
};
