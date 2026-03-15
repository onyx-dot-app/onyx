import { z } from "zod";

/**
 * Convert a Zod schema to a human-readable type string for LLM prompts.
 *
 * Examples:
 *   z.string()              → "string"
 *   z.number().optional()   → "number?"
 *   z.enum(["a", "b"])      → '"a" | "b"'
 *   z.boolean()             → "boolean"
 *   z.array(z.string())     → "string[]"
 */
export function zodToTypeString(schema: z.ZodTypeAny): string {
  return describeType(schema, false);
}

function describeType(
  schema: z.ZodTypeAny,
  isOptionalContext: boolean,
): string {
  // Unwrap optional/nullable
  if (schema instanceof z.ZodOptional) {
    const inner = describeType(schema.unwrap(), true);
    return `${inner}?`;
  }

  if (schema instanceof z.ZodNullable) {
    const inner = describeType(schema.unwrap(), false);
    return `${inner} | null`;
  }

  if (schema instanceof z.ZodDefault) {
    const inner = describeType(schema.removeDefault(), true);
    const suffix = isOptionalContext ? "" : "?";
    return `${inner}${suffix}`;
  }

  // Primitives
  if (schema instanceof z.ZodString) return "string";
  if (schema instanceof z.ZodNumber) return "number";
  if (schema instanceof z.ZodBoolean) return "boolean";
  if (schema instanceof z.ZodNull) return "null";

  // Enum
  if (schema instanceof z.ZodEnum) {
    const values = schema.options as string[];
    return values.map((v) => `"${v}"`).join(" | ");
  }

  if (schema instanceof z.ZodNativeEnum) {
    return "enum";
  }

  // Literal
  if (schema instanceof z.ZodLiteral) {
    const val = schema.value;
    if (typeof val === "string") return `"${val}"`;
    return String(val);
  }

  // Array
  if (schema instanceof z.ZodArray) {
    const inner = describeType(schema.element, false);
    // Wrap complex types in parens for clarity
    const needsParens = inner.includes("|") || inner.includes("&");
    return needsParens ? `(${inner})[]` : `${inner}[]`;
  }

  // Object
  if (schema instanceof z.ZodObject) {
    const shape = schema.shape as Record<string, z.ZodTypeAny>;
    const entries = Object.entries(shape).map(([key, val]) => {
      const typeStr = describeType(val, false);
      const isOpt = val.isOptional();
      return `${key}${isOpt ? "?" : ""}: ${typeStr.replace(/\?$/, "")}`;
    });
    return `{ ${entries.join(", ")} }`;
  }

  // Union
  if (schema instanceof z.ZodUnion) {
    const options = (schema as z.ZodUnion<[z.ZodTypeAny, ...z.ZodTypeAny[]]>)
      .options;
    return options.map((o: z.ZodTypeAny) => describeType(o, false)).join(" | ");
  }

  // Record
  if (schema instanceof z.ZodRecord) {
    const valueType = describeType(schema.element, false);
    return `Record<string, ${valueType}>`;
  }

  // Tuple
  if (schema instanceof z.ZodTuple) {
    const items = (schema as z.ZodTuple<[z.ZodTypeAny, ...z.ZodTypeAny[]]>)
      .items;
    return `[${items
      .map((i: z.ZodTypeAny) => describeType(i, false))
      .join(", ")}]`;
  }

  // Any / Unknown
  if (schema instanceof z.ZodAny) return "any";
  if (schema instanceof z.ZodUnknown) return "unknown";

  return "unknown";
}

/**
 * Generate a function-signature-style string for a component's props schema.
 *
 * Example: `Button(label: string, main?: boolean, primary?: boolean)`
 */
export function schemaToSignature(
  name: string,
  schema: z.ZodObject<z.ZodRawShape>,
): string {
  const shape = schema.shape;
  const params = Object.entries(shape).map(([key, zodType]) => {
    const type = zodType as z.ZodTypeAny;
    const isOpt = type.isOptional();
    const typeStr = zodToTypeString(type).replace(/\?$/, "");
    return `${key}${isOpt ? "?" : ""}: ${typeStr}`;
  });

  return `${name}(${params.join(", ")})`;
}
