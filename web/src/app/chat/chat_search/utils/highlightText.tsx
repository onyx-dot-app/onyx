import React from "react";

/**
 * Highlights matching query terms in text.
 * Returns JSX with highlighted spans.
 */
export function highlightText(text: string, query: string): React.ReactNode {
  if (!query || !text) {
    return text;
  }

  // Split query into individual terms
  const terms = query.toLowerCase().trim().split(/\s+/);

  // Escape special regex characters
  const escapeRegex = (str: string) =>
    str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // Create regex pattern that matches any of the terms
  const pattern = terms.map(escapeRegex).join("|");
  const regex = new RegExp(`(${pattern})`, "gi");

  // Split text by matches
  const parts = text.split(regex);

  return (
    <>
      {parts.map((part, index) => {
        // Check if this part matches any search term
        const isMatch = terms.some(
          (term) => part.toLowerCase() === term.toLowerCase()
        );

        return isMatch ? (
          <mark
            key={index}
            className="bg-yellow-200 dark:bg-yellow-900/50 text-inherit font-medium rounded px-0.5"
          >
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        );
      })}
    </>
  );
}
