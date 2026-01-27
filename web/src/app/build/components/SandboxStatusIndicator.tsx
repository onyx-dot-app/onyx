"use client";

import { motion, AnimatePresence } from "motion/react";

import {
  useSession,
  useIsPreProvisioning,
  useIsPreProvisioningReady,
  useIsPreProvisioningFailed,
} from "@/app/build/hooks/useBuildSessionStore";
import { Card } from "@/components/ui/card";
import Text from "@/refresh-components/texts/Text";

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
  idle: { color: "bg-status-warning-05", pulse: false, label: "Sandbox idle" },
  sleeping: {
    color: "bg-status-info-05",
    pulse: false,
    label: "Sandbox sleeping",
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
} as const;

type Status = keyof typeof STATUS_CONFIG;

interface SandboxStatusIndicatorProps {}

/**
 * Derives the current sandbox status from session state or pre-provisioning state.
 *
 * Priority:
 * 1. Actual sandbox status from backend (if session has sandbox info)
 * 2. Session exists but no sandbox info → "running" (optimistic for consumed pre-provisioned sessions)
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
): Status {
  // 1. Backend is source of truth when available
  if (session?.sandbox) {
    return session.sandbox.status as Status;
  }
  // 2. Session exists but no sandbox info - assume running
  // (This handles consumed pre-provisioned sessions before sandbox loads)
  if (session) {
    return "running";
  }
  // 3. Pre-provisioning failed
  if (isFailed) {
    return "failed";
  }
  // 4. No session - check pre-provisioning state (welcome page)
  if (isPreProvisioning) {
    return "provisioning";
  }
  // 5. Pre-provisioning ready but not consumed
  if (isReady) {
    return "ready";
  }
  // 6. No session, no pre-provisioning state - loading
  return "loading";
}

/**
 * Displays the current sandbox status with a colored indicator dot.
 *
 * Shows actual sandbox state when a session exists, otherwise shows
 * pre-provisioning state (provisioning/ready).
 */
export default function SandboxStatusIndicator(
  _props: SandboxStatusIndicatorProps = {}
) {
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
  const { color, pulse, label } = STATUS_CONFIG[status];

  return (
    <motion.div layout transition={{ duration: 0.3, ease: "easeInOut" }}>
      <Card className="flex items-center gap-2 p-2 overflow-hidden">
        <div
          className={`w-2 h-2 rounded-full shrink-0 ${color} ${
            pulse ? "animate-pulse" : ""
          }`}
        />
        <AnimatePresence mode="wait">
          <motion.span
            key={status}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.2 }}
          >
            <Text text05>{label}</Text>
          </motion.span>
        </AnimatePresence>
      </Card>
    </motion.div>
  );
}
