import SvgSearch from "@/icons/search";
import React, { KeyboardEvent, ChangeEvent } from "react";

interface SearchBarProps {
  query: string;
  setQuery: (query: string) => void;
  onSearch: () => void;
}

export function SearchBar({ query, setQuery, onSearch }: SearchBarProps) {
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
    <div className="flex items-center w-full border rounded-08 p-padding-button">
      <SvgSearch className="h-[1.2rem] w-[1.2rem] stroke-text-04" />
      <textarea
        autoFocus
        className={`flex items-center flex-grow px-padding-button outline-none overflow-hidden whitespace-normal resize-none bg-transparent leading-[1.5rem] h-[1.5rem]`}
        role="textarea"
        aria-multiline
        placeholder="Search..."
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        suppressContentEditableWarning={true}
      />
    </div>
  );
}
