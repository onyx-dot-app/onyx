import type { Library, PromptOptions } from "../types";
import { schemaToSignature } from "./introspector";

/**
 * Auto-generate a system prompt section from a component library.
 *
 * The generated prompt teaches the LLM:
 * 1. The GenUI Lang syntax
 * 2. Available components with signatures
 * 3. Streaming guidelines
 * 4. User-provided examples and rules
 */
export function generatePrompt(
  library: Library,
  options?: PromptOptions,
): string {
  const sections: string[] = [];

  // ── Header ──
  sections.push(`# Structured UI Output (GenUI Lang)

When the user's request benefits from structured UI (tables, cards, buttons, layouts), respond using GenUI Lang — a compact, line-oriented markup. Otherwise respond in plain markdown.`);

  // ── Syntax ──
  sections.push(`## Syntax

Each line declares a variable: \`name = expression\`

Expressions:
- \`ComponentName(arg1, arg2, key: value)\` — component with positional or named args
- \`[a, b, c]\` — array
- \`{key: value}\` — object
- \`"string"\`, \`42\`, \`true\`, \`false\`, \`null\` — literals
- \`variableName\` — reference to a previously defined variable

Rules:
- PascalCase identifiers are component types
- camelCase identifiers are variable references
- Positional args map to props in the order defined below
- The last statement is the root element (or name one \`root\`)
- Lines inside brackets/parens can span multiple lines
- Lines that don't match \`name = expression\` are treated as plain text`);

  // ── Components ──
  const grouped = groupComponents(library);
  const componentLines: string[] = [];

  for (const [group, components] of grouped) {
    if (group) {
      componentLines.push(`\n### ${group}`);
    }

    for (const comp of components) {
      const sig = schemaToSignature(comp.name, comp.props);
      componentLines.push(`- \`${sig}\` — ${comp.description}`);
    }
  }

  sections.push(`## Available Components\n${componentLines.join("\n")}`);

  // ── Streaming Guidelines ──
  if (options?.streaming !== false) {
    sections.push(`## Streaming Guidelines

- Define variables before referencing them
- Each line is independently parseable — the UI updates as each line completes
- Keep variable names short and descriptive
- Build up complex UIs incrementally: define data first, then layout`);
  }

  // ── Examples ──
  if (options?.examples && options.examples.length > 0) {
    const exampleLines = options.examples.map(
      (ex) => `### ${ex.description}\n\`\`\`\n${ex.code}\n\`\`\``,
    );
    sections.push(`## Examples\n\n${exampleLines.join("\n\n")}`);
  }

  // ── Additional Rules ──
  if (options?.additionalRules && options.additionalRules.length > 0) {
    const ruleLines = options.additionalRules.map((r) => `- ${r}`);
    sections.push(`## Additional Guidelines\n\n${ruleLines.join("\n")}`);
  }

  return sections.join("\n\n");
}

function groupComponents(library: Library): [
  string | undefined,
  {
    name: string;
    description: string;
    props: import("zod").ZodObject<import("zod").ZodRawShape>;
  }[],
][] {
  const groups = new Map<string | undefined, typeof result>();

  type ComponentEntry = {
    name: string;
    description: string;
    props: import("zod").ZodObject<import("zod").ZodRawShape>;
  };
  const result: ComponentEntry[] = [];

  for (const [, comp] of library.components) {
    const group = comp.group;
    if (!groups.has(group)) {
      groups.set(group, []);
    }
    groups.get(group)!.push(comp);
  }

  return Array.from(groups.entries());
}
