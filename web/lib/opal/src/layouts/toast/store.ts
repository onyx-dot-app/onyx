import { useEffect, useSyncExternalStore } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ToastLevel = "success" | "error" | "warning" | "info" | "default";

export interface ToastOptions {
  message: string;
  /** @default "info" */
  level?: ToastLevel;
  description?: string;
  /** Milliseconds before auto-dismiss. Infinity keeps the toast persistent. @default 4000 */
  duration?: number;
  /** Shows the close button. @default true */
  dismissible?: boolean;
}

export interface Toast extends ToastOptions {
  id: string;
  createdAt: number;
  /** True while the exit animation plays. */
  leaving?: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const MAX_VISIBLE_TOASTS = 3;
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
const timers = new Map<string, ReturnType<typeof setTimeout>>();

let nextId = 0;

function notify() {
  subscribers.forEach((cb) => cb());
}

function addToast(options: ToastOptions): string {
  const id = `toast-${++nextId}-${Date.now()}`;
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

  toasts = [...toasts, entry];
  notify();

  if (duration !== Infinity) {
    const timer = setTimeout(() => {
      removeToast(id);
    }, duration);
    timers.set(id, timer);
  }

  return id;
}

function removeToast(id: string): void {
  const timer = timers.get(id);
  if (timer) {
    clearTimeout(timer);
    timers.delete(id);
  }
  toasts = toasts.filter((t) => t.id !== id);
  notify();
}

function setAutoDismiss(id: string, duration: number): void {
  const existing = timers.get(id);
  if (existing) {
    clearTimeout(existing);
    timers.delete(id);
  }
  if (duration === Infinity) {
    return;
  }
  const timer = setTimeout(() => {
    removeToast(id);
  }, duration);
  timers.set(id, timer);
}

function markLeaving(id: string): void {
  toasts = toasts.map((t) => (t.id === id ? { ...t, leaving: true } : t));
  notify();
}

function clearAll(): void {
  timers.forEach((timer) => clearTimeout(timer));
  timers.clear();
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
  dismiss: (id: string) => void;
  clearAll: () => void;
  /**
   * Reset (or cancel) a toast's auto-dismiss timer. Pass `Infinity` to make
   * the toast persistent.
   */
  setAutoDismiss: (id: string, duration: number) => void;
  /** @internal Flags the toast as leaving so the exit animation plays. Caller dismisses after the animation. */
  _markLeaving: (id: string) => void;
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
  dismiss: removeToast,
  clearAll,
  setAutoDismiss,
  _markLeaving: markLeaving,
});

// ---------------------------------------------------------------------------
// React hooks
// ---------------------------------------------------------------------------

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
};
