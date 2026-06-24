"use client";

import { MessageCard } from "@opal/components";
import type { RichStr, StatusVariants } from "@opal/types";

import { useBannerDismiss } from "@/hooks/useBannerDismiss";
import { useMainContainerOffset } from "@/hooks/useMainContainerOffset";

interface AppBannerProps {
  variant: StatusVariants;
  title: string | RichStr;
  description?: string | RichStr;
  /**
   * localStorage key for per-device dismissal. Omit for a non-dismissible
   * banner (no close button).
   */
  dismissKey?: string;
}

/**
 * Shared host for top-of-app status banners. Owns the "where/how" — aligning a
 * fixed Opal `MessageCard` to the main content container and persisting
 * dismissal — so each caller only owns the "what/when" (copy, variant, and the
 * visibility condition that decides whether to render it at all).
 */
export default function AppBanner({
  variant,
  title,
  description,
  dismissKey,
}: AppBannerProps) {
  const { left, width } = useMainContainerOffset();
  const { dismissed, dismiss } = useBannerDismiss(dismissKey);

  if (dismissed) return null;

  return (
    <div
      className="fixed top-3 z-toast flex justify-center px-3 pointer-events-none"
      style={{ left, width: width || undefined }}
    >
      <div className="w-full max-w-3xl pointer-events-auto">
        <MessageCard
          variant={variant}
          title={title}
          description={description}
          onClose={dismissKey ? dismiss : undefined}
        />
      </div>
    </div>
  );
}
