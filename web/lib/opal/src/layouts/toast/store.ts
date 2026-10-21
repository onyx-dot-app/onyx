"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";
import { SvgRefreshCw } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ToastLevel = "success" | "error" | "warning" | "info" | "default";

/**
 * An icon button left of the close button. A click runs it and the toast
 * stays: a retry that fails again replaces it in place. An action that should
 * close the toast dismisses it in `onClick`.
 */
export interface ToastAction {
  icon: IconFunctionComponent;
  /** The button's tooltip and accessible name. */
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  /** Firing a toast with the id of a live one replaces it in place. */
  id?: string;
  message: string;
  /** @default "info" */
  level?: ToastLevel;
  description?: string;
  /** Milliseconds before auto-dismiss. Infinity keeps the toast persistent. @default 4000 */
  duration?: number;
  /** Shows the close button. @default true */
  dismissible?: boolean;
  action?: ToastAction;
}

export interface Toast extends ToastOptions {
  id: string;
  createdAt: number;
  /** True while the exit animation plays. */
  leaving?: boolean;
  /**
   * True once a leaving toast has slid away and its space starts to close.
   * Until then it keeps its slot, so the next toast rises out of the pile as
   * the stack moves up, in one motion.
   */
  collapsing?: boolean;
  /**
   * True for a toast closed while in the pile: it leaves out of sight, rather
   * than sliding off from a slot.
   */
  leavingFromPile?: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const MAX_VISIBLE_TOASTS = 3;
// Matches opal-toast-leave in styles.css: a 200ms slide and fade, then a
// 300ms collapse in step with the pile's transitions.
const LEAVE_SLIDE_MS = 200;
const LEAVE_DURATION_MS = 500;
const DEFAULT_DURATION = 4000;
const TOAST_CONSOLE_METHOD: Record<
  ToastLevel,
  "log" | "warn" | "error" | "info"
> = {
  error: "error",
  warning: "warn",
  info: "info",
  success: "log",
  default: "log",
};

// ---------------------------------------------------------------------------
// Module-level store (external to React)
// ---------------------------------------------------------------------------

let toasts: Toast[] = [];
const subscribers = new Set<() => void>();

// Auto-dismiss counts down only while a toast is on show: a toast collapsed
// into the pile, or any toast while the pile is expanded, keeps the time it
// has left and resumes when it shows again.
const remaining = new Map<string, number>();
const running = new Map<
  string,
  { timer: ReturnType<typeof setTimeout>; startedAt: number }
>();
let timersPaused = false;

let nextId = 0;

function notify() {
  subscribers.forEach((cb) => cb());
}

function startTimer(id: string): void {
  const left = remaining.get(id);
  if (left === undefined || left === Infinity || running.has(id)) return;
  const timer = setTimeout(() => {
    running.delete(id);
    remaining.delete(id);
    closeToast(id);
  }, left);
  running.set(id, { timer, startedAt: Date.now() });
}

function pauseTimer(id: string): void {
  const run = running.get(id);
  if (!run) return;
  clearTimeout(run.timer);
  running.delete(id);
  const left = remaining.get(id);
  if (left !== undefined) {
    remaining.set(id, Math.max(0, left - (Date.now() - run.startedAt)));
  }
}

function forgetTimer(id: string): void {
  const run = running.get(id);
  if (run) clearTimeout(run.timer);
  running.delete(id);
  remaining.delete(id);
}

/** Runs the timers of the toasts on show and pauses the rest. */
function syncTimers(): void {
  const shown = new Set(
    timersPaused ? [] : shownToasts(toasts).map((t) => t.id)
  );
  for (const t of toasts) {
    if (t.leaving) continue;
    if (shown.has(t.id)) startTimer(t.id);
    else pauseTimer(t.id);
  }
}

/**
 * The toasts holding the stack's slots: the newest MAX_VISIBLE_TOASTS, where
 * a leaving toast holds its slot until its space starts to close.
 */
export function shownToasts(list: Toast[]): Toast[] {
  return list.filter((t) => !t.collapsing).slice(-MAX_VISIBLE_TOASTS);
}

function addToast(options: ToastOptions): string {
  const id = options.id ?? `toast-${++nextId}-${Date.now()}`;
  const duration = options.duration ?? DEFAULT_DURATION;

  const level = options.level ?? "info";

  const entry: Toast = {
    ...options,
    id,
    level,
    dismissible: options.dismissible ?? true,
    createdAt: Date.now(),
  };

  const method = TOAST_CONSOLE_METHOD[level];
  if (entry.description) {
    console[method](`[Toast] ${entry.message}`, entry.description);
  } else {
    console[method](`[Toast] ${entry.message}`);
  }

  forgetTimer(id);
  remaining.set(id, duration);
  toasts = toasts.some((t) => t.id === id)
    ? toasts.map((t) => (t.id === id ? entry : t))
    : [...toasts, entry];
  notify();
  syncTimers();

  return id;
}

function removeToast(id: string): void {
  forgetTimer(id);
  toasts = toasts.filter((t) => t.id !== id);
  notify();
  syncTimers();
}

/**
 * Animates a toast out, then removes it. Every close goes through here: the
 * close button, a timeout, `toast.dismiss`, and `useErrorToast` when its
 * error clears.
 */
function closeToast(id: string): void {
  const current = toasts.find((t) => t.id === id);
  if (!current || current.leaving) return;
  forgetTimer(id);
  markLeaving(id);
  // Toasts are replaced, never changed, so the entry identifies this close.
  // A toast fired with this id while this one left replaces it and leaves on
  // its own timers: each step here touches only the entry this close made.
  let entry = toasts.find((t) => t.id === id);
  setTimeout(() => {
    if (toasts.find((t) => t.id === id) !== entry) return;
    // Slid away: its space closes, and the next toast rises out of the pile
    // into the freed slot. That toast's timer starts now.
    toasts = toasts.map((t) => (t.id === id ? { ...t, collapsing: true } : t));
    entry = toasts.find((t) => t.id === id);
    notify();
    syncTimers();
  }, LEAVE_SLIDE_MS);
  setTimeout(() => {
    if (toasts.find((t) => t.id === id) !== entry) return;
    removeToast(id);
  }, LEAVE_DURATION_MS);
}

function setAutoDismiss(id: string, duration: number): void {
  forgetTimer(id);
  remaining.set(id, duration);
  syncTimers();
}

/** Pauses every timer, e.g. while the pile is expanded for reading. */
function setTimersPaused(paused: boolean): void {
  timersPaused = paused;
  syncTimers();
}

function markLeaving(id: string): void {
  const fromPile = !shownToasts(toasts).some((t) => t.id === id);
  toasts = toasts.map((t) =>
    t.id === id ? { ...t, leaving: true, leavingFromPile: fromPile } : t
  );
  notify();
}

function clearAll(): void {
  running.forEach((run) => clearTimeout(run.timer));
  running.clear();
  remaining.clear();
  toasts = [];
  notify();
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

function getSnapshot(): Toast[] {
  return toasts;
}

// ---------------------------------------------------------------------------
// Imperative API (works anywhere: components, hooks, plain .ts files)
// ---------------------------------------------------------------------------

interface ToastFn {
  (options: ToastOptions): string;
  success: (
    message: string,
    opts?: Omit<ToastOptions, "message" | "level">
  ) => string;
  error: (
    message: string,
    opts?: Omit<ToastOptions, "message" | "level">
  ) => string;
  warning: (
    message: string,
    opts?: Omit<ToastOptions, "message" | "level">
  ) => string;
  info: (
    message: string,
    opts?: Omit<ToastOptions, "message" | "level">
  ) => string;
  /** Animates the toast out, then removes it. */
  dismiss: (id: string) => void;
  /** Removes every toast at once, without animating. */
  clearAll: () => void;
  /**
   * Reset (or cancel) a toast's auto-dismiss timer. Pass `Infinity` to make
   * the toast persistent.
   */
  setAutoDismiss: (id: string, duration: number) => void;
}

function toastBase(options: ToastOptions): string {
  return addToast(options);
}

export const toast: ToastFn = Object.assign(toastBase, {
  success: (message: string, opts?: Omit<ToastOptions, "message" | "level">) =>
    addToast({ ...opts, message, level: "success" }),
  error: (message: string, opts?: Omit<ToastOptions, "message" | "level">) =>
    addToast({ ...opts, message, level: "error" }),
  warning: (message: string, opts?: Omit<ToastOptions, "message" | "level">) =>
    addToast({ ...opts, message, level: "warning" }),
  info: (message: string, opts?: Omit<ToastOptions, "message" | "level">) =>
    addToast({ ...opts, message, level: "info" }),
  dismiss: closeToast,
  clearAll,
  setAutoDismiss,
});

// ---------------------------------------------------------------------------
// React hooks
// ---------------------------------------------------------------------------

export interface UseErrorToastOptions {
  /** The toast's id: callers sharing an id share one toast. */
  id: string;
  message: string;
  /** Adds a retry button, with `label` as its tooltip. */
  retry?: { label: string; onRetry: () => void };
}

/**
 * Shows a persistent error toast while `error` is set, for a fetch that
 * failed. A new error replaces it; it goes when the error clears or the
 * caller unmounts.
 */
export function useErrorToast(
  error: unknown,
  { id, message, retry }: UseErrorToastOptions
) {
  // Read at click time, so an unstable callback does not re-raise the toast.
  const onRetryRef = useRef(retry?.onRetry);
  useEffect(() => {
    onRetryRef.current = retry?.onRetry;
  });
  const retryLabel = retry?.label;
  const hasError = error != null && error !== false;
  // Each error raises the toast. One already shown is replaced in place, so
  // a retry that fails again leaves it standing rather than replaying it.
  useEffect(() => {
    if (!hasError) return;
    addToast({
      id,
      message,
      level: "error",
      duration: Infinity,
      action:
        retryLabel === undefined
          ? undefined
          : {
              icon: SvgRefreshCw,
              label: retryLabel,
              onClick: () => onRetryRef.current?.(),
            },
    });
  }, [error, hasError, id, message, retryLabel]);
  // Removed only when the error clears or the caller unmounts, never
  // between two errors.
  useEffect(() => {
    if (!hasError) return;
    return () => closeToast(id);
  }, [hasError, id]);
}

export function useToast() {
  useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return { toast, dismiss: toast.dismiss, clearAll: toast.clearAll };
}

interface ToastFromQueryMessages {
  [key: string]: {
    message: string;
    type?: ToastLevel | null;
  };
}

/**
 * Reads a `?message=<key>` query param on mount, fires the matching toast,
 * and strips the param from the URL.
 */
export function useToastFromQuery(messages: ToastFromQueryMessages) {
  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search);
    const messageValue = searchParams.get("message");

    if (messageValue && messageValue in messages) {
      searchParams.delete("message");
      const query = searchParams.toString();
      const newSearch = query ? `?${query}` : "";
      window.history.replaceState(
        null,
        "",
        window.location.pathname + newSearch + window.location.hash
      );
      const spec = messages[messageValue];
      if (spec !== undefined) {
        toast({
          message: spec.message,
          level: spec.type ?? "info",
        });
      }
    }
    // Fires once on mount by design, the query param is consumed and removed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

// ---------------------------------------------------------------------------
// Store accessors
// ---------------------------------------------------------------------------

export const toastStore = {
  subscribe,
  getSnapshot,
  setTimersPaused,
};
