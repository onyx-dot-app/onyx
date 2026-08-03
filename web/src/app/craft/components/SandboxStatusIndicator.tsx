"use client";

import { motion, AnimatePresence } from "motion/react";
import { cn } from "@opal/utils";

import {
  useSession,
  useIsPreProvisioning,
  useIsPreProvisioningReady,
  useIsPreProvisioningFailed,
} from "@/app/craft/hooks/useBuildSessionStore";
import { Text } from "@opal/components";
import type { SandboxRuntimeStatus } from "@/app/craft/types/streamingTypes";

export type SandboxDisplayStatus = SandboxRuntimeStatus | "ready" | "loading";

interface SandboxStatusConfig {
  color: string;
  pulse: boolean;
  label: string;
}

const STATUS_CONFIG = {
  provisioning: {
    color: "bg-status-warning-05",
    pulse: true,
    label: "Initializing sandbox...",
  },
  running: {
    color: "bg-status-success-05",
    pulse: false,
    label: "Sandbox running",
  },
  sleeping: {
    color: "bg-status-info-05",
    pulse: false,
    label: "Sandbox sleeping",
  },
  restoring: {
    color: "bg-status-warning-05",
    pulse: true,
    label: "Restoring session...",
  },
  terminated: {
    color: "bg-status-error-05",
    pulse: false,
    label: "Sandbox terminated",
  },
  failed: {
    color: "bg-status-error-05",
    pulse: false,
    label: "Failed to provision sandbox",
  },
  ready: {
    color: "bg-status-success-05",
    pulse: false,
    label: "Sandbox ready",
  },
  loading: {
    color: "bg-text-03",
    pulse: true,
    label: "Finding sandbox...",
  },
} as const satisfies Record<SandboxDisplayStatus, SandboxStatusConfig>;

interface SandboxStatusIndicatorViewProps {
  status: SandboxDisplayStatus;
}

export function SandboxStatusIndicatorView({
  status,
}: SandboxStatusIndicatorViewProps) {
  const { color, pulse, label } = STATUS_CONFIG[status];

  return (
    <motion.div layout transition={{ duration: 0.3, ease: "easeInOut" }}>
      <div className="flex items-center gap-2 p-2 overflow-hidden rounded-12 border border-border-01 bg-background-neutral-00">
        <div
          className={cn(
            "w-2 h-2 rounded-full shrink-0",
            color,
            pulse && "animate-pulse"
          )}
        />
        <AnimatePresence mode="wait">
          <motion.span
            key={status}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.2 }}
          >
            <Text font="main-ui-body" color="text-05" nowrap>
              {label}
            </Text>
          </motion.span>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

/**
 * Derives the current sandbox status from session state or pre-provisioning state.
 *
 * Priority:
 * 1. Session runtime status (backend status or client-owned restoration)
 * 2. Session exists but no sandbox info → "loading"
 * 3. Pre-provisioning failed → "failed"
 * 4. Pre-provisioning in progress → "provisioning" (only when no session - welcome page)
 * 5. Pre-provisioning ready (not yet consumed) → "ready"
 * 6. Default → "loading" (gray, finding sandbox)
 *
 * IMPORTANT: Pre-provisioning state is checked AFTER session existence because
 * pre-provisioning is for NEW sessions. When viewing an existing session, we
 * should show that session's status, not the background pre-provisioning state.
 */
function deriveSandboxStatus(
  session: ReturnType<typeof useSession>,
  isPreProvisioning: boolean,
  isReady: boolean,
  isFailed: boolean
): SandboxDisplayStatus {
  if (session?.sandbox) {
    return session.sandbox.status;
  }
  // A session without sandbox data has not established a runtime state yet.
  if (session) {
    return "loading";
  }
  if (isFailed) {
    return "failed";
  }
  if (isPreProvisioning) {
    return "provisioning";
  }
  if (isReady) {
    return "ready";
  }
  return "loading";
}

/**
 * Displays the current sandbox status with a colored indicator dot.
 *
 * Shows actual sandbox state when a session exists, otherwise shows
 * pre-provisioning state (provisioning/ready).
 */
export default function SandboxStatusIndicator() {
  const session = useSession();
  const isPreProvisioning = useIsPreProvisioning();
  const isReady = useIsPreProvisioningReady();
  const isFailed = useIsPreProvisioningFailed();

  const status = deriveSandboxStatus(
    session,
    isPreProvisioning,
    isReady,
    isFailed
  );

  return <SandboxStatusIndicatorView status={status} />;
}
