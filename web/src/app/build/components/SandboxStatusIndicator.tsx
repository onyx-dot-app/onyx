"use client";

import { motion, AnimatePresence } from "motion/react";

import {
  useSession,
  useIsPreProvisioning,
  useIsPreProvisioningReady,
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
  terminated: {
    color: "bg-status-error-05",
    pulse: false,
    label: "Sandbox terminated",
  },
  failed: {
    color: "bg-status-error-05",
    pulse: false,
    label: "Sandbox failed",
  },
  ready: {
    color: "bg-status-success-05",
    pulse: false,
    label: "Sandbox ready",
  },
} as const;

type Status = keyof typeof STATUS_CONFIG;

interface SandboxStatusIndicatorProps {}

/**
 * Derives the current sandbox status from session state or pre-provisioning state.
 *
 * Priority:
 * 1. Actual sandbox status (if session exists with sandbox)
 * 2. Pre-provisioning state (provisioning/ready)
 * 3. Default to provisioning
 */
function deriveSandboxStatus(
  session: ReturnType<typeof useSession>,
  isPreProvisioning: boolean,
  isReady: boolean
): Status {
  if (session?.sandbox) {
    return session.sandbox.status as Status;
  }
  if (isPreProvisioning) {
    return "provisioning";
  }
  if (isReady) {
    return "ready";
  }
  return "provisioning";
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

  const status = deriveSandboxStatus(session, isPreProvisioning, isReady);
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
