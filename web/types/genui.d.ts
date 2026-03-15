// Type declarations for GenUI packages.
// These packages live at ../packages/genui/ and are transpiled by Next.js.
// Full type checking happens via their own tsconfigs; these stubs
// satisfy the web type-checker without pulling in the full source tree.

declare module "@onyx/genui" {
  import type { ZodObject, ZodRawShape } from "zod";

  export interface ComponentDef<
    T extends ZodObject<ZodRawShape> = ZodObject<ZodRawShape>,
  > {
    name: string;
    description: string;
    group?: string;
    props: T;
    component: unknown;
  }

  export interface Library {
    components: ReadonlyMap<string, ComponentDef>;
    resolve(name: string): ComponentDef | undefined;
    prompt(options?: Record<string, unknown>): string;
    paramMap(): Map<string, unknown[]>;
  }

  export interface ActionEvent {
    actionId: string;
    payload?: unknown;
  }

  export function defineComponent<T extends ZodObject<ZodRawShape>>(
    config: ComponentDef<T>
  ): ComponentDef<T>;

  export function createLibrary(
    components: ComponentDef[],
    options?: Record<string, unknown>
  ): Library;

  export function parse(
    input: string,
    library: Library
  ): { root: unknown; statements: unknown[]; errors: unknown[] };
}

declare module "@onyx/genui-react" {
  import type { Library, ActionEvent } from "@onyx/genui";

  export interface RendererProps {
    response: string | null;
    library: Library;
    isStreaming?: boolean;
    onAction?: (event: ActionEvent) => void;
    fallbackToMarkdown?: boolean;
    className?: string;
  }

  export function Renderer(props: RendererProps): React.JSX.Element | null;
  export function useTriggerAction(): (
    actionId: string,
    payload?: unknown
  ) => void;
  export function useIsStreaming(): boolean;
}

declare module "@onyx/genui-onyx" {
  import type { Library } from "@onyx/genui";

  export const onyxLibrary: Library;
  export const onyxPromptAddons: {
    rules: string[];
    examples: Array<{ input: string; description: string }>;
  };
}
