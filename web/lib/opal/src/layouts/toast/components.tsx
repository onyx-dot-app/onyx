"use client";

import { useCallback, useState, useSyncExternalStore } from "react";
import { cn } from "@opal/utils";
import { MessageCard, Text } from "@opal/components";
import {
  MAX_VISIBLE_TOASTS,
  toast,
  toastStore,
  type Toast,
} from "@opal/layouts/toast/store";

const ANIMATION_DURATION = 200; // matches tailwind fade-out-scale (0.2s)
const MAX_TOAST_MESSAGE_LENGTH = 150;
// How long a toast lingers after the user clicks to expand it. Long enough to
// read a multi-line stack trace or API error without forcing a manual dismiss.
const EXPANDED_DURATION_MS = 30000;

function buildDescription(
  t: Toast,
  errorAppendix?: string
): string | undefined {
  const parts: string[] = [];
  if (t.description) parts.push(t.description);
  if (t.level === "error" && errorAppendix) parts.push(errorAppendix);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

interface ExpandedDetailsProps {
  message: string;
}

function ExpandedDetails({ message }: ExpandedDetailsProps) {
  return (
    <div className="max-h-72 overflow-y-auto whitespace-pre-wrap px-3 py-2 wrap-break-word">
      <Text font="secondary-body" color="text-03" as="p">
        {message}
      </Text>
    </div>
  );
}

interface ToastContainerProps {
  errorAppendix?: string;
}

function ToastContainer({ errorAppendix }: ToastContainerProps) {
  const allToasts = useSyncExternalStore(
    toastStore.subscribe,
    toastStore.getSnapshot,
    toastStore.getSnapshot
  );
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const visible = allToasts.slice(-MAX_VISIBLE_TOASTS);

  const handleClose = useCallback((id: string) => {
    toast._markLeaving(id);
    setTimeout(() => {
      toast.dismiss(id);
      setExpandedIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }, ANIMATION_DURATION);
  }, []);

  const handleExpand = useCallback((t: Toast) => {
    setExpandedIds((prev) => {
      if (prev.has(t.id)) return prev;
      const next = new Set(prev);
      next.add(t.id);
      return next;
    });
    // Restart auto-dismiss with reading time for the full message. Persistent
    // toasts stay persistent.
    if (t.duration !== Infinity) {
      toast.setAutoDismiss(t.id, EXPANDED_DURATION_MS);
    }
  }, []);

  if (visible.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className="fixed bottom-4 right-4 z-(--z-toast) flex w-full max-w-(--toast-width) flex-col items-end gap-2"
    >
      {visible.map((t) => {
        const isTruncatable = t.message.length > MAX_TOAST_MESSAGE_LENGTH;
        const isExpanded = expandedIds.has(t.id);
        const truncatedTitle = isTruncatable
          ? t.message.slice(0, MAX_TOAST_MESSAGE_LENGTH) + "…"
          : t.message;
        const expandable = isTruncatable && !isExpanded;
        return (
          <div
            key={t.id}
            className={cn(
              "w-full",
              t.leaving ? "animate-fade-out-scale" : "animate-fade-in-scale",
              expandable && "cursor-pointer"
            )}
            onClick={
              expandable
                ? (e) => {
                    // Don't intercept clicks on the inner close button.
                    if (
                      (e.target as HTMLElement).closest(
                        'button[aria-label="Close"]'
                      )
                    ) {
                      return;
                    }
                    handleExpand(t);
                  }
                : undefined
            }
          >
            <MessageCard
              variant={t.level ?? "info"}
              title={truncatedTitle}
              description={buildDescription(t, errorAppendix)}
              padding="xs"
              onClose={t.dismissible ? () => handleClose(t.id) : undefined}
              bottomChildren={
                isExpanded ? <ExpandedDetails message={t.message} /> : undefined
              }
            />
          </div>
        );
      })}
    </div>
  );
}

interface ToastProviderProps {
  children: React.ReactNode;

  /** Appended to every error toast's description (e.g. a support link). */
  errorAppendix?: string;
}

/**
 * Renders the app's toast stack bottom-right, driven by the module-level
 * store in `toast/store` (fire toasts from anywhere via `toast(...)` or the
 * `useToast` hook). Long messages truncate and expand on click.
 */
function ToastProvider({ children, errorAppendix }: ToastProviderProps) {
  return (
    <>
      {children}
      <ToastContainer errorAppendix={errorAppendix} />
    </>
  );
}

export { ToastProvider, type ToastProviderProps };
