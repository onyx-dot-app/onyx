import { useContext, useCallback } from "react";
import type { ActionEvent } from "@onyx/genui";
import { StreamingContext, ActionContext } from "./context";

/**
 * Returns true while the LLM is still generating output.
 */
export function useIsStreaming(): boolean {
  return useContext(StreamingContext).isStreaming;
}

/**
 * Returns a function to trigger an action event (e.g. button click).
 * Components call this with an actionId and optional payload.
 */
export function useTriggerAction(): (
  actionId: string,
  payload?: Record<string, unknown>
) => void {
  const handler = useContext(ActionContext);

  return useCallback(
    (actionId: string, payload?: Record<string, unknown>) => {
      if (handler) {
        const event: ActionEvent = { actionId, payload };
        handler(event);
      }
    },
    [handler]
  );
}
