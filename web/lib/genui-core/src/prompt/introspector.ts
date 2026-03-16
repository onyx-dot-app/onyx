import { z } from "zod";

/**
 * Convert a Zod schema to a human-readable type string for LLM prompts.
 *
 * Uses `_def.typeName` instead of `instanceof` to avoid issues with
 * multiple Zod copies in the module graph.
 */
export function zodToTypeString(schema: z.ZodTypeAny): string {
  return describeType(schema, false);
}

function describeType(
  schema: z.ZodTypeAny,
  isOptionalContext: boolean
): string {
  const typeName = schema._def?.typeName as string | undefined;

  // Unwrap optional/nullable
  if (typeName === "ZodOptional") {
    const inner = describeType(
      (schema as z.ZodOptional<z.ZodTypeAny>).unwrap(),
      true
    );
    return `${inner}?`;
  }

  if (typeName === "ZodNullable") {
    const inner = describeType(
      (schema as z.ZodNullable<z.ZodTypeAny>).unwrap(),
      false
    );
    return `${inner} | null`;
  }

  if (typeName === "ZodDefault") {
    const inner = describeType(
      (schema as z.ZodDefault<z.ZodTypeAny>).removeDefault(),
      true
    );
    const suffix = isOptionalContext ? "" : "?";
    return `${inner}${suffix}`;
  }

  // Primitives
  if (typeName === "ZodString") return "string";
  if (typeName === "ZodNumber") return "number";
  if (typeName === "ZodBoolean") return "boolean";
  if (typeName === "ZodNull") return "null";

  // Enum
  if (typeName === "ZodEnum") {
    const values = (schema as z.ZodEnum<[string, ...string[]]>)
      .options as string[];
    return values.map((v) => `"${v}"`).join(" | ");
  }

  if (typeName === "ZodNativeEnum") {
    return "enum";
  }

  // Literal
  if (typeName === "ZodLiteral") {
    const val = (schema as z.ZodLiteral<unknown>).value;
    if (typeof val === "string") return `"${val}"`;
    return String(val);
  }

  // Array
  if (typeName === "ZodArray") {
    const inner = describeType(
      (schema as z.ZodArray<z.ZodTypeAny>).element,
      false
    );
    const needsParens = inner.includes("|") || inner.includes("&");
    return needsParens ? `(${inner})[]` : `${inner}[]`;
  }

  // Object
  if (typeName === "ZodObject") {
    const shape = (schema as z.ZodObject<z.ZodRawShape>).shape as Record<
      string,
      z.ZodTypeAny
    >;
    const entries = Object.entries(shape).map(([key, val]) => {
      const typeStr = describeType(val, false);
      const isOpt = val.isOptional();
      return `${key}${isOpt ? "?" : ""}: ${typeStr.replace(/\?$/, "")}`;
    });
    return `{ ${entries.join(", ")} }`;
  }

  // Union
  if (typeName === "ZodUnion") {
    const options = (schema as z.ZodUnion<[z.ZodTypeAny, ...z.ZodTypeAny[]]>)
      .options;
    return options.map((o: z.ZodTypeAny) => describeType(o, false)).join(" | ");
  }

  // Record
  if (typeName === "ZodRecord") {
    const valueType = describeType((schema as z.ZodRecord).element, false);
    return `Record<string, ${valueType}>`;
  }

  // Tuple
  if (typeName === "ZodTuple") {
    const items = (schema as z.ZodTuple<[z.ZodTypeAny, ...z.ZodTypeAny[]]>)
      .items;
    return `[${items
      .map((i: z.ZodTypeAny) => describeType(i, false))
      .join(", ")}]`;
  }

  // Any / Unknown
  if (typeName === "ZodAny") return "any";
  if (typeName === "ZodUnknown") return "unknown";

  return "unknown";
}

/**
 * Generate a function-signature-style string for a component's props schema.
 *
 * Example: `Button(label: string, main?: boolean, primary?: boolean)`
 */
export function schemaToSignature(
  name: string,
  schema: z.ZodObject<z.ZodRawShape>
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
