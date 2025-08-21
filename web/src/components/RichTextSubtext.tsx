import React from "react";

interface RichTextSubtextProps {
  text: string;
  className?: string;
}

/**
 * Component that renders text with clickable links.
 * Detects URLs in the text and converts them to clickable links.
 * Also supports markdown-style links like [text](url).
 * NOTE: we should be careful not to use this component in a way that displays text from external sources
 * because it could be used to create links to malicious sites. Right now it's just used to make links
 * to our docs in connector setup pages
 */
export function RichTextSubtext({
  text,
  className = "",
}: RichTextSubtextProps) {
  // Function to parse text and create React elements
  const parseText = (input: string): React.ReactNode[] => {
    const elements: React.ReactNode[] = [];

    // Regex to match markdown links [text](url) and plain URLs
    const combinedRegex = /(\[([^\]]+)\]\(([^)]+)\))|(https?:\/\/[^\s]+)/g;

    let lastIndex = 0;
    let match;
    let key = 0;

    while ((match = combinedRegex.exec(input)) !== null) {
      // Add text before the match
      if (match.index > lastIndex) {
        elements.push(
          <span key={`text-${key++}`}>
            {input.slice(lastIndex, match.index)}
          </span>
        );
      }

      if (match[1]) {
        // Markdown-style link [text](url)
        const linkText = match[2];
        const url = match[3];
        elements.push(
          <a
            key={`link-${key++}`}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-link hover:text-link-hover underline"
            onClick={(e) => e.stopPropagation()}
          >
            {linkText}
          </a>
        );
      } else if (match[4]) {
        // Plain URL
        const url = match[4];
        elements.push(
          <a
            key={`link-${key++}`}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-link hover:text-link-hover underline"
            onClick={(e) => e.stopPropagation()}
          >
            {url}
          </a>
        );
      }

      lastIndex = match.index + match[0].length;
    }

    // Add remaining text after the last match
    if (lastIndex < input.length) {
      elements.push(
        <span key={`text-${key++}`}>{input.slice(lastIndex)}</span>
      );
    }

    return elements;
  };

  return <div className={className}>{parseText(text)}</div>;
}
