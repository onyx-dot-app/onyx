import { z } from "zod";
import type {
  ComponentDef,
  Library,
  ParamDef,
  ParamMap,
  PromptOptions,
} from "./types";
import { generatePrompt } from "./prompt/generator";

/**
 * Build ordered param definitions from a Zod object schema.
 * Ordering matches the shape key order (which is insertion order in JS objects).
 */
function buildParamDefs(schema: z.ZodObject<z.ZodRawShape>): ParamDef[] {
  const shape = schema.shape;
  return Object.entries(shape).map(([name, zodType]) => {
    const unwrapped = zodType as z.ZodTypeAny;
    const isOptional = unwrapped.isOptional();

    return {
      name,
      required: !isOptional,
      zodType: unwrapped,
    };
  });
}

interface CreateLibraryOptions {
  /** Default prompt options merged with per-call options */
  defaultPromptOptions?: PromptOptions;
}

/**
 * Create a component library from an array of component definitions.
 */
export function createLibrary(
  components: ComponentDef[],
  options?: CreateLibraryOptions
): Library {
  const map = new Map<string, ComponentDef>();

  for (const comp of components) {
    if (map.has(comp.name)) {
      throw new Error(`Duplicate component name: "${comp.name}"`);
    }
    map.set(comp.name, comp);
  }

  const cachedParamMap = new Map<string, ParamDef[]>();

  return {
    components: map,

    resolve(name: string): ComponentDef | undefined {
      return map.get(name);
    },

    prompt(promptOptions?: PromptOptions): string {
      const merged: PromptOptions = {
        ...options?.defaultPromptOptions,
        ...promptOptions,
        additionalRules: [
          ...(options?.defaultPromptOptions?.additionalRules ?? []),
          ...(promptOptions?.additionalRules ?? []),
        ],
        examples: [
          ...(options?.defaultPromptOptions?.examples ?? []),
          ...(promptOptions?.examples ?? []),
        ],
      };
      return generatePrompt(this, merged);
    },

    paramMap(): ParamMap {
      if (cachedParamMap.size === 0) {
        for (const [name, comp] of map) {
          cachedParamMap.set(name, buildParamDefs(comp.props));
        }
      }
      return cachedParamMap;
    },
  };
}
