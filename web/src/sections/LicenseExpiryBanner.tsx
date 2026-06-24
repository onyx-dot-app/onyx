"use client";

import type { ExpiryWarningStage } from "@/lib/billing/interfaces";
import { useLicense } from "@/hooks/useLicense";
import AppBanner from "@/sections/AppBanner";

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
    // Re-show once per day during the grace period so the countdown stays seen.
    const today = new Date().toISOString().slice(0, 10);
    return `${base}:${today}`;
  }
  return base;
}

export default function LicenseExpiryBanner() {
  const { data } = useLicense();

  const stage = data?.expiry_warning_stage ?? "none";
  const expiresAt = data?.expires_at ?? null;
  const graceDays = computeGraceDaysRemaining(data?.grace_period_end ?? null);
  const hasLicense = data?.has_license ?? false;

  if (!hasLicense || stage === "none") {
    return null;
  }

  const copy = buildCopy(stage, expiresAt, graceDays);
  if (!copy) {
    return null;
  }

  return (
    <AppBanner
      variant={copy.variant}
      title={copy.title}
      description={copy.description}
      dismissKey={dismissKey(stage, expiresAt)}
    />
  );
}
