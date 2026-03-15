import type {
  ASTNode,
  ElementNode,
  Library,
  ParseError,
  ParseResult,
  Statement,
} from "../types";
import { Parser } from "./parser";
import { autoClose } from "./autoclose";
import { resolveReferences } from "./resolver";
import { validateAndTransform } from "./validator";

/**
 * Streaming parser for GenUI Lang.
 *
 * Design: each `push(chunk)` appends to the buffer. We split on newlines,
 * cache results for complete lines, and re-parse only the last (partial) line
 * with auto-closing applied.
 *
 * This gives us O(1) work per chunk for complete lines and O(n) only for the
 * current partial line — ideal for LLM token-by-token streaming.
 */
export interface StreamParser {
  push(chunk: string): ParseResult;
  result(): ParseResult;
  reset(): void;
}

export function createStreamingParser(library: Library): StreamParser {
  let buffer = "";
  let cachedStatements: Statement[] = [];
  let cachedLineCount = 0;
  let lastResult: ParseResult = { statements: [], root: null, errors: [] };

  function parseAll(): ParseResult {
    const allErrors: ParseError[] = [];

    // Split into lines
    const lines = buffer.split("\n");
    const completeLines = lines.slice(0, -1);
    const partialLine = lines[lines.length - 1] ?? "";

    // Re-use cached statements for lines we've already parsed
    const newCompleteCount = completeLines.length;
    if (newCompleteCount > cachedLineCount) {
      // Parse new complete lines
      const newLines = completeLines.slice(cachedLineCount).join("\n");
      if (newLines.trim()) {
        const parser = Parser.fromSource(newLines);
        const { statements, errors } = parser.parse();
        cachedStatements = [...cachedStatements, ...statements];
        allErrors.push(...errors);
      }
      cachedLineCount = newCompleteCount;
    }

    // Parse partial line with auto-closing
    let partialStatements: Statement[] = [];
    if (partialLine.trim()) {
      const closed = autoClose(partialLine);
      const parser = Parser.fromSource(closed);
      const { statements, errors } = parser.parse();
      partialStatements = statements;
      // Don't report errors for partial lines — they're expected during streaming
      void errors;
    }

    const allStatements = [...cachedStatements, ...partialStatements];

    // Resolve references
    const { root, errors: resolveErrors } = resolveReferences(allStatements);
    allErrors.push(...resolveErrors);

    // Transform to element tree
    let rootElement: ElementNode | null = null;
    if (root) {
      const { element, errors: validateErrors } = validateAndTransform(
        root,
        library,
      );
      rootElement = element;
      allErrors.push(...validateErrors);
    }

    lastResult = {
      statements: allStatements,
      root: rootElement as ASTNode | null,
      errors: allErrors,
    };

    return lastResult;
  }

  return {
    push(chunk: string): ParseResult {
      buffer += chunk;
      return parseAll();
    },

    result(): ParseResult {
      return lastResult;
    },

    reset(): void {
      buffer = "";
      cachedStatements = [];
      cachedLineCount = 0;
      lastResult = { statements: [], root: null, errors: [] };
    },
  };
}
