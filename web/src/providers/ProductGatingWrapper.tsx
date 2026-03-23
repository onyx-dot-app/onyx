"use client";

import { ApplicationStatus } from "@/interfaces/settings";
import { useSettingsContext } from "@/providers/SettingsProvider";
import GatedContentWrapper from "@/components/GatedContentWrapper";

export default function ProductGatingWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  const { settings, settingsLoading } = useSettingsContext();
  const status = settings.application_status;

  if (settingsLoading) return null;

  if (
    status === ApplicationStatus.GATED_ACCESS ||
    status === ApplicationStatus.SEAT_LIMIT_EXCEEDED
  ) {
    return <GatedContentWrapper>{children}</GatedContentWrapper>;
  }

  return children;
}
