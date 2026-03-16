import { z } from "zod";

// ── Token types produced by the tokenizer ──

export enum TokenType {
  Identifier = "Identifier",
  String = "String",
  Number = "Number",
  Boolean = "Boolean",
  Null = "Null",
  Equals = "Equals",
  Colon = "Colon",
  Comma = "Comma",
  LParen = "LParen",
  RParen = "RParen",
  LBracket = "LBracket",
  RBracket = "RBracket",
  LBrace = "LBrace",
  RBrace = "RBrace",
  Newline = "Newline",
  EOF = "EOF",
}

export interface Token {
  type: TokenType;
  value: string;
  offset: number;
  line: number;
  column: number;
}

// ── AST nodes produced by the parser ──

export type ASTNode =
  | ComponentNode
  | ArrayNode
  | ObjectNode
  | LiteralNode
  | ReferenceNode;

export interface ComponentNode {
  kind: "component";
  name: string;
  args: ArgumentNode[];
}

export interface ArgumentNode {
  key: string | null; // null = positional
  value: ASTNode;
}

export interface ArrayNode {
  kind: "array";
  elements: ASTNode[];
}

export interface ObjectNode {
  kind: "object";
  entries: { key: string; value: ASTNode }[];
}

export interface LiteralNode {
  kind: "literal";
  value: string | number | boolean | null;
}

export interface ReferenceNode {
  kind: "reference";
  name: string;
}

// ── Resolved element tree (post-resolution) ──

export interface ElementNode {
  kind: "element";
  component: string;
  props: Record<string, unknown>;
  children: ElementNode[];
}

export interface TextElementNode {
  kind: "text";
  content: string;
}

export type ResolvedNode = ElementNode | TextElementNode;

// ── Statement = one line binding ──

export interface Statement {
  name: string;
  value: ASTNode;
}

// ── Parse result ──

export interface ParseError {
  message: string;
  line: number;
  column: number;
  offset?: number;
}

export interface ParseResult {
  statements: Statement[];
  root: ASTNode | null;
  errors: ParseError[];
}

// ── Component definition ──

export interface ComponentDef<
  T extends z.ZodObject<z.ZodRawShape> = z.ZodObject<z.ZodRawShape>,
> {
  name: string;
  description: string;
  props: T;
  component: unknown; // framework-agnostic — React renderer narrows this
  group?: string;
}

// ── Param mapping (for positional → named resolution) ──

export interface ParamDef {
  name: string;
  required: boolean;
  description?: string;
  zodType: z.ZodTypeAny;
}

export type ParamMap = Map<string, ParamDef[]>;

// ── Library ──

export interface Library {
  components: ReadonlyMap<string, ComponentDef>;
  resolve(name: string): ComponentDef | undefined;
  prompt(options?: PromptOptions): string;
  paramMap(): ParamMap;
}

export interface PromptOptions {
  /** Extra rules or guidelines appended to the prompt */
  additionalRules?: string[];
  /** Example GenUI Lang snippets */
  examples?: { description: string; code: string }[];
  /** If true, include streaming guidelines */
  streaming?: boolean;
}

// ── Action events (from interactive components) ──

export interface ActionEvent {
  actionId: string;
  payload?: Record<string, unknown>;
}
