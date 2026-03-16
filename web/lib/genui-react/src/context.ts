import { createContext, useContext } from "react";
import type { Library, ActionEvent } from "@onyx/genui";

// ── Library Context ──

export const LibraryContext = createContext<Library | null>(null);

export function useLibrary(): Library {
  const library = useContext(LibraryContext);
  if (!library) {
    throw new Error(
      "useLibrary must be used within a <Renderer> or <LibraryContext.Provider>"
    );
  }
  return library;
}

// ── Streaming Context ──

export interface StreamingState {
  isStreaming: boolean;
}

export const StreamingContext = createContext<StreamingState>({
  isStreaming: false,
});

// ── Action Context ──

export type ActionHandler = (event: ActionEvent) => void;

export const ActionContext = createContext<ActionHandler | null>(null);

export function useActionHandler(): ActionHandler | null {
  return useContext(ActionContext);
}
