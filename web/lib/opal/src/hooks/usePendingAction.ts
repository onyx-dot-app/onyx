"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface PendingAction<Args extends unknown[]> {
  /**
   * Runs the action, unless a run is still pending: a call made meanwhile is
   * dropped, so a double click or a second pick cannot race the first. A
   * rejection clears the pending state and passes on to the caller.
   */
  run: (...args: Args) => Promise<void>;
  /** True while a run's promise is unsettled; a sync action never sets it. */
  isPending: boolean;
}

/**
 * Wraps an async action (a save, a delete) with its pending state, for a
 * control that must disable itself until the action settles.
 */
export default function usePendingAction<Args extends unknown[]>(
  action: (...args: Args) => void | Promise<void>
): PendingAction<Args> {
  const [isPending, setIsPending] = useState(false);
  // A ref, not the state, so two calls in one event both see the first.
  const pendingRef = useRef(false);
  const actionRef = useRef(action);
  useEffect(() => {
    actionRef.current = action;
  }, [action]);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const run = useCallback(async (...args: Args) => {
    if (pendingRef.current) return;
    const result = actionRef.current(...args);
    if (!(result instanceof Promise)) return;
    pendingRef.current = true;
    setIsPending(true);
    try {
      await result;
    } finally {
      pendingRef.current = false;
      if (mountedRef.current) setIsPending(false);
    }
  }, []);

  return { run, isPending };
}
