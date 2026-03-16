import React from "react";

interface FallbackRendererProps {
  content: string;
}

/**
 * Fallback renderer for responses that aren't valid GenUI Lang.
 * Renders as plain text with basic formatting.
 *
 * In the Onyx integration, this would be replaced with the existing
 * markdown renderer. This is a minimal standalone fallback.
 */
export function FallbackRenderer({ content }: FallbackRendererProps) {
  // Split into paragraphs, preserving code blocks
  const blocks = content.split(/\n\n+/);

  return (
    <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
      {blocks.map((block, i) => {
        // Code blocks
        if (block.startsWith("```")) {
          const lines = block.split("\n");
          const code = lines.slice(1, -1).join("\n");
          return (
            <pre
              key={i}
              style={{
                backgroundColor: "#f3f4f6",
                padding: "12px",
                borderRadius: "6px",
                overflow: "auto",
                fontSize: "13px",
                fontFamily: "monospace",
              }}
            >
              <code>{code}</code>
            </pre>
          );
        }

        return (
          <p key={i} style={{ margin: "0 0 1em 0" }}>
            {block}
          </p>
        );
      })}
    </div>
  );
}
