// ── Main entry point ──
export { Renderer } from "./Renderer";
export type { RendererProps } from "./Renderer";

// ── Sub-components ──
export { StreamingRenderer } from "./StreamingRenderer";
export { NodeRenderer } from "./NodeRenderer";
export { FallbackRenderer } from "./FallbackRenderer";
export { ErrorBoundary } from "./ErrorBoundary";

// ── Contexts ──
export {
  LibraryContext,
  StreamingContext,
  ActionContext,
  useLibrary,
  useActionHandler,
} from "./context";
export type { StreamingState, ActionHandler } from "./context";

// ── Hooks ──
export { useIsStreaming, useTriggerAction } from "./hooks";
