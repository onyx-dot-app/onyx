import { z } from "zod";
import type { ComponentDef } from "./types";

interface DefineComponentConfig<T extends z.ZodObject<z.ZodRawShape>> {
  name: string;
  description: string;
  props: T;
  component: unknown;
  group?: string;
}

/**
 * Define a GenUI component with typed props via Zod schema.
 * The `component` field is framework-agnostic (typed as `unknown` in core).
 * React bindings narrow this to `React.FC`.
 */
export function defineComponent<T extends z.ZodObject<z.ZodRawShape>>(
  config: DefineComponentConfig<T>,
): ComponentDef<T> {
  if (!/^[A-Z][a-zA-Z0-9]*$/.test(config.name)) {
    throw new Error(
      `Component name "${config.name}" must be PascalCase (start with uppercase, alphanumeric only)`,
    );
  }

  return {
    name: config.name,
    description: config.description,
    props: config.props,
    component: config.component,
    group: config.group,
  };
}
