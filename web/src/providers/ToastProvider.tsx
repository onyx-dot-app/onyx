"use client";

import { useCallback, useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";
import Message from "@/refresh-components/messages/Message";
import { NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK } from "@/lib/constants";
import { toast, toastStore, MAX_VISIBLE_TOASTS } from "@/hooks/useToast";
import type { Toast, ToastLevel } from "@/hooks/useToast";

const ANIMATION_DURATION = 200; // matches tailwind fade-out-scale (0.2s)

function levelProps(level: ToastLevel): Record<string, boolean> {
  switch (level) {
    case "success":
      return { success: true };
    case "error":
      return { error: true };
    case "warning":
      return { warning: true };
    case "info":
      return { info: true };
    default:
      return { default: true };
  }
}

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

  // NOTE (@raunakab):
  //
  // Keep this here for debugging purposes.
  // useOnMount(() => {
  //   toast.success("Test success toast", { duration: Infinity });
  //   toast.error("Test error toast", { duration: Infinity });
  //   toast.warning("Test warning toast", { duration: Infinity });
  //   toast.info("Test info toast", { duration: Infinity });
  // });

  if (visible.length === 0) return null;

  return (
    <div
      data-testid="toast-container"
      className={cn(
        "fixed bottom-4 right-4 z-[10000]",
        "flex flex-col gap-2 items-end"
      )}
    >
      {visible.map((t) => (
        <div
          key={t.id}
          className={cn(
            t.leaving ? "animate-fade-out-scale" : "animate-fade-in-scale"
          )}
        >
          <Message
            flash
            medium
            {...levelProps(t.level ?? "info")}
            text={t.message}
            description={buildDescription(t)}
            close={t.dismissible}
            onClose={() => handleClose(t.id)}
            actions={t.actionLabel ? t.actionLabel : undefined}
            onAction={t.onAction}
          />
        </div>
      ))}
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
