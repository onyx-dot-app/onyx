import React, { KeyboardEvent, ChangeEvent, useContext } from "react";

import { MagnifyingGlass } from "@phosphor-icons/react";
interface FullSearchBarProps {
  disabled: boolean;
  query: string;
  setPopup: (popupSpec: PopupSpec | null) => void;
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
  previousSearch: string;
}

import { useState, useEffect, useRef } from "react";
import { SendIcon } from "../icons/icons";
import { Divider } from "@tremor/react";
import { CustomTooltip } from "../tooltip/CustomTooltip";
import KeyboardSymbol from "@/lib/browserUtilities";
import { SettingsContext } from "../settings/SettingsProvider";
import { HorizontalSourceSelector, SourceSelector } from "./filtering/Filters";
import { CCPairBasicInfo, DocumentSet, Tag } from "@/lib/types";
import { SourceMetadata } from "@/lib/search/interfaces";
import { PopupSpec } from "../admin/connectors/Popup";

export const AnimatedToggle = ({
  isOn,
  handleToggle,
}: {
  isOn: boolean;
  handleToggle: () => void;
}) => {
  const commandSymbol = KeyboardSymbol();

  const [width, setWidth] = useState("auto");
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const updateWidth = () => {
      if (containerRef.current && contentRef.current) {
        const newWidth = contentRef.current.scrollWidth;
        setWidth(`${newWidth}px`);
      }
    };

    updateWidth();
    window.addEventListener("resize", updateWidth);
    return () => window.removeEventListener("resize", updateWidth);
  }, [isOn]);

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
        className="my-auto ml-auto flex jusitfy-end items-center cursor-pointer transition-all duration-300 ease-in-out overflow-hidden"
        style={{ width }}
        onClick={handleToggle}
      >
        <div
          ref={contentRef}
          className={`flex group ml-auto items-center transition-all duration-300 ease-in-out ml-auto`}
        >
          <div
            className={`
            w-10 h-6 flex items-center rounded-full p-1 transition-all duration-300 ease-in-out
            ${isOn ? "bg-background-400" : "bg-background-200"}
          `}
          >
            <div
              className={`
              bg-white w-4 h-4 rounded-full group-hover:scale-[.8] shadow-md transform transition-all duration-300 ease-in-out
              ${!isOn ? "" : "translate-x-4"}
            `}
            ></div>
          </div>
          <p className="flex ml-2 w-[40px]">
            <span
              className={`no-underline text-sm transition-all duration-300 ease-in-out ${
                isOn ? "opacity-0  translate-y-10 w-0" : "opacity-100"
              }`}
            >
              Fast
            </span>
            <span
              className={`text-sm transition-all duration-300 ease-in-out ${
                isOn ? "opacity-100 " : "opacity-0 -translate-y-10 w-0"
              }`}
            >
              Agentic
            </span>
          </p>
        </div>
      </div>
    </CustomTooltip>
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
  setPopup,
  finalAvailableSources,
  tags,
  previousSearch,
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
        bg-background-100
        [&:has(textarea:focus)]::ring-1
        [&:has(textarea:focus)]::ring-black
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
          bg-background-100
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
        className={`flex ${showingSidebar ? " 2xl:justify-between" : "2xl:justify-end"} justify-between 4xl:justify-end w-full items-center space-x-3 py-3 px-4`}
      >
        <div className={`-my-1 4xl:hidden ${!showingSidebar && "2xl:hidden"}`}>
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
        <div className="flex my-auto gap-x-3">
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
                className={`text-emphasis ${disabled && "opacity-50"} text-white p-1 rounded-full ${
                  query ? "bg-background-800" : "bg-[#D7D7D7]"
                }`}
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
    <div className="flex justify-center">
      <div className="flex items-center w-full opacity-100 border-2 border-border rounded-lg px-4 py-2 focus-within:border-accent bg-background-search">
        <MagnifyingGlass className="text-emphasis" />
        <textarea
          autoFocus
          className="flex-grow ml-2 h-6 outline-none placeholder-default overflow-hidden whitespace-normal resize-none"
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
