/** The service a key is for, e.g. "openai" or "exa". */
export type ApiTokenPlatform = string;

/** Where a saved key is used. */
export type ApiTokenUsageKind =
  | "llm_provider"
  | "image_generation"
  | "voice_provider"
  | "embedding_provider"
  | "web_search_provider"
  | "web_content_provider"
  | "tracing_provider"
  | "hook"
  | "unstructured";

export interface ApiTokenUsage {
  kind: ApiTokenUsageKind;
  name: string;
}

/** A saved key as the list endpoint returns it. */
export interface ApiTokenView {
  id: number;
  platform: ApiTokenPlatform;
  masked_value: string;
  usages: ApiTokenUsage[];
}

/**
 * A key field's value, and the shape a request sends it in: a key typed into
 * the field, or a saved key picked from the list (an edit that leaves the
 * key alone sends the key it already has).
 */
export type ApiTokenValue =
  | { type: "new"; value: string }
  | { type: "existing"; id: number };
