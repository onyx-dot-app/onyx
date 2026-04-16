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
  default: "default",
  success: "success",
  error: "error",
  warning: "warning",
  info: "info",
};

function buildDescription(toast: Toast): string | undefined {
  const parts: string[] = [];
  if (toast.description) parts.push(toast.description);
  if (toast.level === "error" && NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK) {
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
      className="fixed bottom-4 right-4 z-[10000] flex flex-col gap-2 items-end w-[420px]"
    >
      {visible.map((toast) => {
        const text =
          toast.message.length > MAX_TOAST_MESSAGE_LENGTH
            ? toast.message.slice(0, MAX_TOAST_MESSAGE_LENGTH) + "…"
            : toast.message;

        return (
          <div
            key={toast.id}
            className={cn(
              "w-full",
              toast.leaving ? "animate-fade-out-scale" : "animate-fade-in-scale"
            )}
          >
            <MessageCard
              variant={LEVEL_TO_VARIANT[toast.level ?? "info"]}
              title={text}
              description={buildDescription(toast)}
              onClose={
                toast.dismissible ? () => handleClose(toast.id) : undefined
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
