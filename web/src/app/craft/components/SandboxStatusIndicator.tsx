"use client";

import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";

import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { Text } from "@opal/components";
import type { SandboxRuntimeStatus } from "@/app/craft/types/streamingTypes";

export type SandboxDisplayStatus = SandboxRuntimeStatus | "ready" | "loading";

interface SandboxStatusConfig {
  color: string;
  pulse: boolean;
}

const STATUS_CONFIG = {
  provisioning: {
    color: "bg-status-warning-05",
    pulse: true,
  },
  running: {
    color: "bg-status-success-05",
    pulse: false,
  },
  sleeping: {
    color: "bg-status-info-05",
    pulse: false,
  },
  restoring: {
    color: "bg-status-warning-05",
    pulse: true,
  },
  terminated: {
    color: "bg-status-error-05",
    pulse: false,
  },
  failed: {
    color: "bg-status-error-05",
    pulse: false,
  },
  ready: {
    color: "bg-status-success-05",
    pulse: false,
  },
  loading: {
    color: "bg-text-03",
    pulse: true,
  },
} as const satisfies Record<SandboxDisplayStatus, SandboxStatusConfig>;

interface SandboxStatusIndicatorViewProps {
  status: SandboxDisplayStatus;
}

export function SandboxStatusIndicatorView({
  status,
}: SandboxStatusIndicatorViewProps) {
  const t = useTranslations("craft.outputWorkspace.status");
  const { color, pulse } = STATUS_CONFIG[status];
  const label = t(status);
  return (
    <div
      data-testid="sandbox-status"
      title={label}
      aria-label={label}
      className="flex h-7 shrink-0 items-center justify-end gap-1.5"
    >
      <div
        className={cn(
          "size-2 rounded-full shrink-0",
          color,
          pulse && "motion-safe:animate-pulse"
        )}
      />
      <Text font="main-ui-muted" color="text-03" wordWrap="whitespace-nowrap">
        {label}
      </Text>
    </div>
  );
}

export default function SandboxStatusIndicator() {
  const status = useBuildSessionStore((state): SandboxDisplayStatus => {
    // Existing sessions take precedence over welcome-page pre-provisioning.
    if (state.currentSessionId)
      return (
        state.sessions.get(state.currentSessionId)?.sandbox?.status ?? "loading"
      );
    const provisioning = state.preProvisioning.status;
    return provisioning === "failed" || provisioning === "ready"
      ? provisioning
      : provisioning === "provisioning"
        ? "provisioning"
        : "loading";
  });

  return <SandboxStatusIndicatorView status={status} />;
}
