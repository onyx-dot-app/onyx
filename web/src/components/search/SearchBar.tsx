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
  showingSidebar: boolean;
}

import {
  TooltipProvider,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { useRef } from "react";
import { SendIcon } from "../icons/icons";
import { Separator } from "@/components/ui/separator";
import { CustomTooltip } from "../tooltip/CustomTooltip";
import KeyboardSymbol from "@/lib/browserUtilities";
import { HorizontalSourceSelector } from "./filtering/Filters";
import { CCPairBasicInfo, DocumentSet, Tag } from "@/lib/types";

export const AnimatedToggle = ({
  isOn,
  handleToggle,
  direction = "top",
}: {
  isOn: boolean;
  handleToggle: () => void;
  direction?: "bottom" | "top";
}) => {
  const commandSymbol = KeyboardSymbol();
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            ref={containerRef}
            className="my-auto ml-auto flex justify-end items-center cursor-pointer"
            onClick={handleToggle}
          >
            <div ref={contentRef} className="flex items-center">
              <div
                className={`
                w-10 h-6 flex items-center rounded-full p-1 transition-all duration-300 ease-in-out 
                ${isOn ? "bg-toggled-background" : "bg-untoggled-background"}
              `}
              >
                <div
                  className={`
                  bg-white w-4 h-4 rounded-full shadow-md transform transition-all duration-300 ease-in-out
                  ${isOn ? "translate-x-4" : ""}
                `}
                ></div>
              </div>
              <p className="ml-2 text-sm">Pro</p>
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent side={direction} backgroundColor="bg-background-200">
          <div className="bg-white my-auto p-6 rounded-lg max-w-sm">
            <h2 className="text-xl text-text-800 font-bold mb-2">
              Agentic Search
            </h2>
            <p className="text-text-700 text-sm mb-4">
              Our most powerful search, have an AI agent guide you to pinpoint
              exactly what you&apos;re looking for.
            </p>
            <Separator />
            <h2 className="text-xl text-text-800 font-bold mb-2">
              Fast Search
            </h2>
            <p className="text-text-700 text-sm mb-4">
              Get quality results immediately, best suited for instant access to
              your documents.
            </p>
            <p className="mt-2 flex text-xs">Shortcut: ({commandSymbol}/)</p>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export default AnimatedToggle;

export const FullSearchBar = ({
  disabled,
  showingSidebar,
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
          resize-none
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
        className={`flex flex-nowrap ${
          showingSidebar ? " 2xl:justify-between" : "2xl:justify-end"
        } justify-between 4xl:justify-end w-full max-w-full items-center space-x-3 py-3 px-4`}
      >
        <div
          className={`-my-1 flex-grow 4xl:hidden ${
            !showingSidebar && "2xl:hidden"
          }`}
        >
          {(ccPairs.length > 0 || documentSets.length > 0) && (
            <HorizontalSourceSelector
              isHorizontal
              {...filterManager}
              showDocSidebar={false}
              availableDocumentSets={finalAvailableDocumentSets}
              existingSources={finalAvailableSources}
              availableTags={tags}
            />
          )}
        </div>
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
                className={`text-emphasis ${
                  disabled || !query
                    ? "bg-disabled-submit-background"
                    : "bg-submit-background"
                } text-white p-1 rounded-full`}
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
      onSearch();
      event.preventDefault();
    }
  };

  return (
    <div className="flex text-text-chatbar justify-center">
      <div className="flex items-center w-full opacity-100 border-2 border-border rounded-lg px-4 py-2 focus-within:border-accent bg-background-search">
        <MagnifyingGlass className="text-emphasis" />
        <textarea
          autoFocus
          className="flex-grow ml-2 h-6 placeholder:text-text-chatbar-subtle outline-none placeholder-default overflow-hidden whitespace-normal resize-none"
          role="textarea"
          aria-multiline
          placeholder="Search..."
          value={query}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          suppressContentEditableWarning={true}
        />
      </div>
    </div>
  );
};
