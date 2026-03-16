import React, { useRef, useMemo } from "react";
import { createStreamingParser } from "@onyx/genui";
import type { Library, ElementNode } from "@onyx/genui";
import { NodeRenderer } from "./NodeRenderer";
import { FallbackRenderer } from "./FallbackRenderer";

interface StreamingRendererProps {
  response: string;
  library: Library;
  isStreaming: boolean;
  fallbackToMarkdown?: boolean;
}

/**
 * Manages a StreamParser instance and feeds it the response string.
 * Re-parses on each update and renders the resulting element tree.
 */
export function StreamingRenderer({
  response,
  library,
  isStreaming,
  fallbackToMarkdown = true,
}: StreamingRendererProps) {
  const lastResponseLenRef = useRef(0);

  // Create parser once per library identity
  const parser = useMemo(() => {
    lastResponseLenRef.current = 0;
    return createStreamingParser(library);
  }, [library]);

  // Feed new chunks to the parser
  if (response.length > lastResponseLenRef.current) {
    const newChunk = response.slice(lastResponseLenRef.current);
    parser.push(newChunk);
    lastResponseLenRef.current = response.length;
  } else if (response.length < lastResponseLenRef.current) {
    // Response was reset (e.g. regeneration)
    parser.reset();
    if (response.length > 0) {
      parser.push(response);
    }
    lastResponseLenRef.current = response.length;
  }

  const result = parser.result();

  // If parsing produced no root and fallback is enabled, render as plain text
  if (!result.root && fallbackToMarkdown) {
    return <FallbackRenderer content={response} />;
  }

  if (!result.root) {
    return null;
  }

  // The root from ParseResult is typed as ASTNode but after validation
  // it's actually an ElementNode. Cast safely.
  const rootElement = result.root as unknown as ElementNode;

  if (rootElement.kind !== "element") {
    if (fallbackToMarkdown) {
      return <FallbackRenderer content={response} />;
    }
    return null;
  }

  return (
    <div data-genui-root="true">
      <NodeRenderer node={rootElement} />
    </div>
  );
}
