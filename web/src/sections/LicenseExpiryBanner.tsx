"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Button } from "@opal/components";
import { SvgAlertCircle, SvgAlertTriangle, SvgX } from "@opal/icons";
import { Content } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ExpiryWarningStage,
  LicenseStatus,
} from "@/lib/billing/interfaces";
import { cn } from "@opal/utils";

const DISMISS_STORAGE_KEY = "license-expiry-banner-dismissed";

interface BannerCopy {
  title: string;
  description: string;
  className: string;
  icon: typeof SvgAlertCircle;
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
      title: `Onyx license expires ${expiresDisplay}`,
      description:
        "Your license will expire in approximately 30 days. Contact your Onyx representative to renew.",
      className: "bg-status-warning-01",
      icon: SvgAlertCircle,
    };
  }
  if (stage === "t_14d") {
    return {
      title: `Onyx license expires ${expiresDisplay}`,
      description:
        "Your license will expire in approximately 2 weeks. Renewal must be completed soon to avoid service interruption.",
      className: "bg-status-warning-01",
      icon: SvgAlertTriangle,
    };
  }
  if (stage === "t_1d") {
    return {
      title: `Onyx license expires tomorrow (${expiresDisplay})`,
      description:
        "Your license expires within 24 hours. Renew immediately to avoid service interruption.",
      className: "bg-status-error-01",
      icon: SvgAlertTriangle,
    };
  }
  if (stage === "grace") {
    return {
      title: `Onyx license expired — ${graceDaysRemaining} grace day(s) remaining`,
      description: `Your license expired on ${expiresDisplay}. Renew immediately to avoid service interruption.`,
      className: "bg-status-error-01",
      icon: SvgAlertTriangle,
    };
  }
  return null;
}

function dismissKey(
  stage: ExpiryWarningStage,
  expiresAt: string | null
): string {
  return `${DISMISS_STORAGE_KEY}:${stage}:${expiresAt ?? "unknown"}`;
}

export default function LicenseExpiryBanner() {
  const { data } = useSWR<LicenseStatus>(
    SWR_KEYS.license,
    errorHandlingFetcher
  );
  const [dismissed, setDismissed] = useState(false);

  const stage = data?.expiry_warning_stage ?? "none";
  const expiresAt = data?.expires_at ?? null;
  const graceDays = data?.grace_days_remaining ?? 0;
  const key = dismissKey(stage, expiresAt);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setDismissed(window.sessionStorage.getItem(key) === "1");
  }, [key]);

  if (!data?.has_license || stage === "none" || dismissed) {
    return null;
  }

  const copy = buildCopy(stage, expiresAt, graceDays);
  if (!copy) return null;

  function handleDismiss() {
    if (typeof window !== "undefined") {
      window.sessionStorage.setItem(key, "1");
    }
    setDismissed(true);
  }

  return (
    <div
      className={cn(
        "fixed top-0 left-0 z-[100] w-full p-3 flex items-start gap-2",
        copy.className
      )}
    >
      <div className="flex-1">
        <Content
          icon={copy.icon}
          title={copy.title}
          description={copy.description}
          sizePreset="main-content"
          variant="section"
        />
      </div>
      <Button
        variant="default"
        prominence="tertiary"
        size="sm"
        icon={SvgX}
        onClick={handleDismiss}
      />
    </div>
  );
}
