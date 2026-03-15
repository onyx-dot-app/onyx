// ── Types ──
export type {
  Token,
  ASTNode,
  ComponentNode,
  ArgumentNode,
  ArrayNode,
  ObjectNode,
  LiteralNode,
  ReferenceNode,
  ElementNode,
  TextElementNode,
  ResolvedNode,
  Statement,
  ParseError,
  ParseResult,
  ComponentDef,
  ParamDef,
  ParamMap,
  Library,
  PromptOptions,
  ActionEvent,
} from "./types";
export { TokenType } from "./types";

// ── Component & Library ──
export { defineComponent } from "./component";
export { createLibrary } from "./library";

// ── Parser ──
export { Tokenizer } from "./parser/tokenizer";
export { Parser } from "./parser/parser";
export { autoClose } from "./parser/autoclose";
export { resolveReferences } from "./parser/resolver";
export { validateAndTransform } from "./parser/validator";
export { createStreamingParser } from "./parser/streaming";
export type { StreamParser } from "./parser/streaming";

// ── Prompt ──
export { generatePrompt } from "./prompt/generator";
export { zodToTypeString, schemaToSignature } from "./prompt/introspector";

// ── Convenience: one-shot parse ──
import type { Library, ParseResult, ElementNode, ASTNode } from "./types";
import { Parser } from "./parser/parser";
import { resolveReferences } from "./parser/resolver";
import { validateAndTransform } from "./parser/validator";

/**
 * One-shot parse: tokenize → parse → resolve → validate.
 */
export function parse(input: string, library: Library): ParseResult {
  const parser = Parser.fromSource(input);
  const { statements, errors: parseErrors } = parser.parse();
  const { root, errors: resolveErrors } = resolveReferences(statements);

  const allErrors = [...parseErrors, ...resolveErrors];

  let rootElement: ElementNode | null = null;
  if (root) {
    const { element, errors: validateErrors } = validateAndTransform(
      root,
      library,
    );
    rootElement = element;
    allErrors.push(...validateErrors);
  }

  return {
    statements,
    root: rootElement as ASTNode | null,
    errors: allErrors,
  };
}
