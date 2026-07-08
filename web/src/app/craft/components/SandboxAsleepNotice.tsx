"use client";

import { useEffect, useState } from "react";
import { Button, Text } from "@opal/components";
import {
  useSession,
  useSessionId,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { useSandboxSleepWatcher } from "@/app/craft/hooks/useSandboxSleepWatcher";

// Waking is always user-initiated — never automatic — so we don't keep pods
// alive forever and defeat idle reaping.
export default function SandboxAsleepNotice() {
  useSandboxSleepWatcher();

  const sessionId = useSessionId();
  const session = useSession();
  const loadSession = useBuildSessionStore((state) => state.loadSession);
  const status = session?.sandbox?.status ?? null;
  const isAsleep = status === "sleeping" || status === "terminated";

  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!isAsleep) setDismissed(false);
  }, [isAsleep]);

  useEffect(() => {
    setDismissed(false);
  }, [sessionId]);

  if (!session || !sessionId || !isAsleep || dismissed) return null;

  const handleWake = () => {
    setDismissed(true);
    loadSession(sessionId, { force: true });
  };

  return (
    <div className="fixed inset-0 z-1400 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-xs"
        onClick={() => setDismissed(true)}
      />

      <div className="relative z-10 w-full max-w-xl mx-4 bg-background-tint-01 rounded-16 shadow-lg border border-border-01">
        <div className="p-6 flex flex-col gap-6">
          <div className="flex items-center justify-center">
            <Text font="heading-h2" color="text-05">
              Your sandbox fell asleep
            </Text>
          </div>

          <div className="flex justify-center text-center">
            <Text font="main-ui-body" color="text-04">
              It went to sleep after a period of inactivity — your work is
              saved. Wake it to keep going.
            </Text>
          </div>

          <div className="flex items-center justify-center gap-3">
            <Button
              variant="default"
              prominence="tertiary"
              onClick={() => setDismissed(true)}
            >
              Dismiss
            </Button>
            <Button variant="default" prominence="primary" onClick={handleWake}>
              Wake sandbox
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
