"use client";

import { ApplicationStatus } from "@/lib/settings/types";
import { useSettings } from "@/lib/settings/hooks";
import GatedContentWrapper from "@/components/GatedContentWrapper";

export default function ProductGatingWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  const settings = useSettings();
  const status = settings.application_status;

  if (settings.isLoading) return null;

  if (
    status === ApplicationStatus.GATED_ACCESS ||
    status === ApplicationStatus.SEAT_LIMIT_EXCEEDED
  ) {
    return <GatedContentWrapper>{children}</GatedContentWrapper>;
  }

  return children;
}
