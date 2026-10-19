import type { MethodSpec, ToolSnapshot } from "@/lib/tools/types";

export type OpenApiDefinition = NonNullable<ToolSnapshot["definition"]>;

/** Schema text the server accepted, with the actions it found. */
export interface CheckedOpenApiSchema {
  text: string;
  definition: OpenApiDefinition;
  methods: MethodSpec[];
}

/**
 * Parses OpenAPI schema text. Trailing commas and Python's `True`, `False`
 * and `None` are accepted, and quoted text is left as it is. Throws on text
 * that is not JSON.
 */
export function parseOpenApiSchema(text: string): OpenApiDefinition {
  const cleaned = text.replace(
    /"(?:\\.|[^"\\])*"|,\s*(?=[}\]])|\b(?:True|False|None)\b/g,
    (token: string) => {
      switch (token) {
        case "True":
          return "true";
        case "False":
          return "false";
        case "None":
          return "null";
        default:
          return token.startsWith(",") ? "" : token;
      }
    }
  );
  return JSON.parse(cleaned);
}

/** Schema text pretty-printed with two-space indentation. Throws like `parseOpenApiSchema`. */
export function formatOpenApiSchema(text: string): string {
  return JSON.stringify(parseOpenApiSchema(text), null, 2);
}
