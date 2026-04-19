"use client";

import { useCallback, useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";
import { MessageCard } from "@opal/components";
import type { StatusVariants } from "@opal/types";
import { NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK } from "@/lib/constants";
import { toast, toastStore, MAX_VISIBLE_TOASTS } from "@/hooks/useToast";
import type { Toast, ToastLevel } from "@/hooks/useToast";

const ANIMATION_DURATION = 200; // matches tailwind fade-out-scale (0.2s)
const MAX_TOAST_MESSAGE_LENGTH = 150;

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

function ToastContainer() {
  const allToasts = useSyncExternalStore(
    toastStore.subscribe,
    toastStore.getSnapshot,
    toastStore.getSnapshot
  );

  const visible = allToasts.slice(-MAX_VISIBLE_TOASTS);

  const handleClose = useCallback((id: string) => {
    toast._markLeaving(id);
    setTimeout(() => {
      toast.dismiss(id);
    }, ANIMATION_DURATION);
  }, []);

  if (visible.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className="fixed bottom-4 right-4 z-[var(--z-toast)] flex flex-col gap-2 items-end max-w-[var(--toast-width)] w-full"
    >
      {visible.map((t) => {
        const text =
          t.message.length > MAX_TOAST_MESSAGE_LENGTH
            ? t.message.slice(0, MAX_TOAST_MESSAGE_LENGTH) + "\u2026"
            : t.message;
        return (
          <div
            key={t.id}
            className={cn(
              "w-full",
              t.leaving ? "animate-fade-out-scale" : "animate-fade-in-scale"
            )}
          >
            <MessageCard
              variant={LEVEL_TO_VARIANT[t.level ?? "info"]}
              title={text}
              description={buildDescription(t)}
              padding="xs"
              onClose={t.dismissible ? () => handleClose(t.id) : undefined}
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
