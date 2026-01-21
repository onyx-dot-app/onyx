"use client";

import { useSession } from "@/app/build/hooks/useBuildSessionStore";
import { usePreProvisioning } from "@/app/build/hooks/usePreProvisioning";
import { Card } from "@/components/ui/card";
import Text from "@/refresh-components/texts/Text";

const STATUS_CONFIG = {
  provisioning: {
    color: "bg-yellow-500",
    pulse: true,
    label: "Initializing sandbox...",
  },
  running: { color: "bg-green-500", pulse: false, label: "Sandbox running" },
  idle: { color: "bg-yellow-500", pulse: false, label: "Sandbox idle" },
  terminated: {
    color: "bg-red-500",
    pulse: false,
    label: "Sandbox terminated",
  },
  failed: { color: "bg-red-500", pulse: false, label: "Sandbox failed" },
  ready: { color: "bg-green-500", pulse: false, label: "Sandbox ready" },
} as const;

type Status = keyof typeof STATUS_CONFIG;

/**
 * Displays the current sandbox status with a colored indicator dot.
 *
 * Shows actual sandbox state when a session exists, otherwise shows
 * pre-provisioning state (provisioning/ready).
 */
export default function SandboxStatusIndicator() {
  const session = useSession();
  const { isPreProvisioning, isReady } = usePreProvisioning();

  // Derive status from actual sandbox state or pre-provisioning state
  let status: Status;
  if (session?.sandbox) {
    status = session.sandbox.status as Status;
  } else if (isPreProvisioning) {
    status = "provisioning";
  } else if (isReady) {
    status = "ready";
  } else {
    status = "provisioning";
  }

  const { color, pulse, label } = STATUS_CONFIG[status];

  return (
    <Card className="flex items-center gap-2 p-2">
      <div
        className={`w-2 h-2 rounded-full ${color} ${
          pulse ? "animate-pulse" : ""
        }`}
      />
      <Text text05>{label}</Text>
    </Card>
  );
}
