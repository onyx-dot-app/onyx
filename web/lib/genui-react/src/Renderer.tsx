import React from "react";
import type { Library, ActionEvent } from "@onyx/genui";
import { LibraryContext, StreamingContext, ActionContext } from "./context";
import { StreamingRenderer } from "./StreamingRenderer";

export interface RendererProps {
  /** Raw GenUI Lang string from the LLM */
  response: string | null;
  /** Component library to render with */
  library: Library;
  /** Is the LLM still generating? */
  isStreaming?: boolean;
  /** Callback for interactive component events */
  onAction?: (event: ActionEvent) => void;
  /** Fall back to plain text for non-parseable responses */
  fallbackToMarkdown?: boolean;
  /** CSS class for the wrapper element */
  className?: string;
}

/**
 * Main entry point for rendering GenUI Lang output.
 *
 * Wraps the streaming renderer with all required contexts.
 */
export function Renderer({
  response,
  library,
  isStreaming = false,
  onAction,
  fallbackToMarkdown = true,
  className,
}: RendererProps) {
  if (!response) return null;

  return (
    <LibraryContext.Provider value={library}>
      <StreamingContext.Provider value={{ isStreaming }}>
        <ActionContext.Provider value={onAction ?? null}>
          <div className={className}>
            <StreamingRenderer
              response={response}
              library={library}
              isStreaming={isStreaming}
              fallbackToMarkdown={fallbackToMarkdown}
            />
          </div>
        </ActionContext.Provider>
      </StreamingContext.Provider>
    </LibraryContext.Provider>
  );
}
