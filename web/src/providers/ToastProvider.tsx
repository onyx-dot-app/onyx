"use client";

import { useCallback, useState, useSyncExternalStore } from "react";
import { cn } from "@opal/utils";
import { MessageCard, Text } from "@opal/components";
import type { StatusVariants } from "@opal/types";
import { NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK } from "@/lib/constants";
import { toast, toastStore, MAX_VISIBLE_TOASTS } from "@/hooks/useToast";
import type { Toast, ToastLevel } from "@/hooks/useToast";

const ANIMATION_DURATION = 200; // matches tailwind fade-out-scale (0.2s)
const MAX_TOAST_MESSAGE_LENGTH = 150;
// How long a toast lingers after the user clicks to expand it. Long enough to
// read a multi-line stack trace / API error without forcing a manual dismiss.
const EXPANDED_DURATION_MS = 30000;

const LEVEL_TO_VARIANT: Record<ToastLevel, StatusVariants> = {
  success: "success",
  error: "error",
  warning: "warning",
  info: "info",
  default: "default",
};

function buildDescription(t: Toast): string | undefined {
  const parts: string[] = [];
  if (t.description) parts.push(t.description);
  if (t.level === "error" && NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK) {
    parts.push(
      "Need help? Join our community at https://discord.gg/4NA5SbzrWb for support!"
    );
  }
  return parts.length > 0 ? parts.join(" ") : undefined;
}

interface ExpandedDetailsProps {
  message: string;
}

function ExpandedDetails({ message }: ExpandedDetailsProps) {
  return (
    <div className="px-3 py-2 max-h-72 overflow-y-auto whitespace-pre-wrap break-words">
      <Text font="secondary-body" color="text-03" as="p">
        {message}
      </Text>
    </div>
  );
}

function ToastContainer() {
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

  const handleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    // Reset the auto-dismiss timer so the user has time to read the full
    // message before it fades.
    toast.setAutoDismiss(id, EXPANDED_DURATION_MS);
  }, []);

  if (visible.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className="fixed bottom-4 right-4 z-[var(--z-toast)] flex flex-col gap-2 items-end max-w-[var(--toast-width)] w-full"
    >
      {visible.map((t) => {
        const isTruncatable = t.message.length > MAX_TOAST_MESSAGE_LENGTH;
        const isExpanded = expandedIds.has(t.id);
        const truncatedTitle = isTruncatable
          ? t.message.slice(0, MAX_TOAST_MESSAGE_LENGTH) + "\u2026"
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
                    handleExpand(t.id);
                  }
                : undefined
            }
          >
            <MessageCard
              variant={LEVEL_TO_VARIANT[t.level ?? "info"]}
              title={truncatedTitle}
              description={buildDescription(t)}
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
}

export default function ToastProvider({ children }: ToastProviderProps) {
  return (
    <>
      {children}
      <ToastContainer />
    </>
  );
}
