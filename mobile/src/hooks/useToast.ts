import { useSyncExternalStore } from "react";

export type ToastLevel = "success" | "error" | "warning" | "info" | "default";

export interface ToastOptions {
  message: string;
  level?: ToastLevel;
  description?: string;
  duration?: number; // ms; default 4000, Infinity = persistent
  dismissible?: boolean;
}

export interface Toast extends ToastOptions {
  id: string;
  level: ToastLevel;
  dismissible: boolean;
}

export const MAX_VISIBLE_TOASTS = 3;
const DEFAULT_DURATION = 4000;

let toasts: Toast[] = [];
const subscribers = new Set<() => void>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();
let nextId = 0;

function notify(): void {
  subscribers.forEach((cb) => cb());
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

// Readonly view of the live array. A defensive copy would break useSyncExternalStore's
// stable-snapshot contract, so the readonly *type* is what stops consumers mutating store state.
function getSnapshot(): readonly Readonly<Toast>[] {
  return toasts;
}

function addToast(options: ToastOptions): string {
  const id = `toast-${++nextId}`;
  const duration = options.duration ?? DEFAULT_DURATION;
  const entry: Toast = {
    ...options,
    id,
    level: options.level ?? "info",
    dismissible: options.dismissible ?? true,
  };
  toasts = [...toasts, entry];
  notify();
  if (duration !== Infinity) {
    timers.set(
      id,
      setTimeout(() => removeToast(id), duration),
    );
  }
  return id;
}

function removeToast(id: string): void {
  const timer = timers.get(id);
  if (timer) {
    clearTimeout(timer);
    timers.delete(id);
  }
  toasts = toasts.filter((entry) => entry.id !== id);
  notify();
}

function clearAll(): void {
  timers.forEach((timer) => clearTimeout(timer));
  timers.clear();
  toasts = [];
  notify();
}

type LevelOptions = Omit<ToastOptions, "message" | "level">;

interface ToastFn {
  (options: ToastOptions): string;
  success: (message: string, opts?: LevelOptions) => string;
  error: (message: string, opts?: LevelOptions) => string;
  warning: (message: string, opts?: LevelOptions) => string;
  info: (message: string, opts?: LevelOptions) => string;
  dismiss: (id: string) => void;
  clearAll: () => void;
}

// Callable from anywhere — components, hooks, and plain .ts modules (e.g. useUpload).
export const toast: ToastFn = Object.assign(
  (options: ToastOptions): string => addToast(options),
  {
    success: (message: string, opts?: LevelOptions): string =>
      addToast({ ...opts, message, level: "success" }),
    error: (message: string, opts?: LevelOptions): string =>
      addToast({ ...opts, message, level: "error" }),
    warning: (message: string, opts?: LevelOptions): string =>
      addToast({ ...opts, message, level: "warning" }),
    info: (message: string, opts?: LevelOptions): string =>
      addToast({ ...opts, message, level: "info" }),
    dismiss: removeToast,
    clearAll,
  },
);

// Subscribes a component (the ToastHost) to the live toast list.
export function useToasts(): readonly Readonly<Toast>[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
