"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { MessageCard } from "@opal/components";
import type { ExpiryWarningStage } from "@/lib/billing/interfaces";
import { useLicense } from "@/hooks/useLicense";

const DISMISS_STORAGE_KEY = "license-expiry-banner-dismissed";

type BannerVariant = "warning" | "error";

interface BannerCopy {
  title: string;
  description: string;
  variant: BannerVariant;
}

function buildCopy(
  stage: ExpiryWarningStage,
  expiresAt: string | null,
  graceDaysRemaining: number
): BannerCopy | null {
  const expiresDisplay = expiresAt
    ? new Date(expiresAt).toLocaleDateString()
    : "soon";

  if (stage === "t_30d") {
    return {
      title: `Your Onyx license expires on ${expiresDisplay}.`,
      description:
        "Renewal is due in approximately 30 days. Contact your Onyx representative to renew.",
      variant: "warning",
    };
  }
  if (stage === "t_14d") {
    return {
      title: `Your Onyx license expires on ${expiresDisplay}.`,
      description:
        "Renewal is due in approximately 2 weeks. Complete renewal soon to avoid service interruption.",
      variant: "warning",
    };
  }
  if (stage === "t_1d") {
    return {
      title: `Your Onyx license expires tomorrow (${expiresDisplay}).`,
      description:
        "Renewal is due within 24 hours. Renew now to avoid service interruption.",
      variant: "error",
    };
  }
  if (stage === "grace") {
    return {
      title: `Your Onyx license expired on ${expiresDisplay}.`,
      description: `${graceDaysRemaining} grace day${
        graceDaysRemaining === 1 ? "" : "s"
      } remaining before access is gated. Renew now.`,
      variant: "error",
    };
  }
  return null;
}

function computeGraceDaysRemaining(gracePeriodEnd: string | null): number {
  if (!gracePeriodEnd) return 0;
  const msLeft = new Date(gracePeriodEnd).getTime() - Date.now();
  if (msLeft <= 0) return 0;
  return Math.max(1, Math.ceil(msLeft / 86400000));
}

function dismissKey(
  stage: ExpiryWarningStage,
  expiresAt: string | null
): string {
  const base = `${DISMISS_STORAGE_KEY}:${stage}:${expiresAt ?? "unknown"}`;
  if (stage === "grace") {
    const today = new Date().toISOString().slice(0, 10);
    return `${base}:${today}`;
  }
  return base;
}

interface LicenseExpiryBannerViewProps {
  stage: ExpiryWarningStage;
  expiresAt: string | null;
  graceDaysRemaining: number;
  onDismiss?: () => void;
}

export function LicenseExpiryBannerView({
  stage,
  expiresAt,
  graceDaysRemaining,
  onDismiss,
}: LicenseExpiryBannerViewProps) {
  const copy = buildCopy(stage, expiresAt, graceDaysRemaining);
  if (!copy) return null;

  return (
    <MessageCard
      variant={copy.variant}
      title={copy.title}
      description={copy.description}
      onClose={onDismiss}
    />
  );
}

function useMainContainerOffset(): { left: number; width: number } {
  const pathname = usePathname();
  const [bounds, setBounds] = useState<{ left: number; width: number }>({
    left: 0,
    width: 0,
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    let target: HTMLElement | null = null;
    let frame = 0;

    function update() {
      const el = document.querySelector<HTMLElement>("[data-main-container]");
      if (el) {
        const rect = el.getBoundingClientRect();
        setBounds({ left: rect.left, width: rect.width });
        if (target !== el) {
          ro.disconnect();
          ro.observe(el);
          target = el;
        }
      } else {
        setBounds({ left: 0, width: window.innerWidth });
        target = null;
      }
    }

    const ro = new ResizeObserver(update);
    const mo = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    });

    update();
    mo.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", update);

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      mo.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [pathname]);

  return bounds;
}

export default function LicenseExpiryBanner() {
  const { data } = useLicense();
  const [dismissed, setDismissed] = useState(false);
  const { left, width } = useMainContainerOffset();

  const stage = data?.expiry_warning_stage ?? "none";
  const expiresAt = data?.expires_at ?? null;
  const graceDays = computeGraceDaysRemaining(data?.grace_period_end ?? null);
  const hasLicense = data?.has_license ?? false;
  const key = dismissKey(stage, expiresAt);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setDismissed(window.localStorage.getItem(key) === "1");
  }, [key]);

  if (!hasLicense || stage === "none" || dismissed) {
    return null;
  }

  function handleDismiss() {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(key, "1");
    }
    setDismissed(true);
  }

  return (
    <div
      className="fixed top-3 z-toast flex justify-center px-3 pointer-events-none"
      style={{ left, width: width || undefined }}
    >
      <div className="w-full max-w-3xl pointer-events-auto">
        <LicenseExpiryBannerView
          stage={stage}
          expiresAt={expiresAt}
          graceDaysRemaining={graceDays}
          onDismiss={handleDismiss}
        />
      </div>
    </div>
  );
}
