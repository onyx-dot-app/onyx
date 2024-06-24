export interface ToolSnapshot {
  id: number;
  name: string;
  description: string;

  // only specified for Custom Tools. OpenAPI schema which represents
  // the tool's API.
  definition: Record<string, any> | null;

  // only specified for Custom Tools. ID of the tool in the codebase.
  in_code_tool_id: string | null;
}

export interface MethodSpec {
  /* Defines a single method that is part of a custom tool. Each method maps to a single 
  action that the LLM can choose to take. */
  name: string;
  summary: string;
  path: string;
  method: string;
  spec: Record<string, any>;
}
