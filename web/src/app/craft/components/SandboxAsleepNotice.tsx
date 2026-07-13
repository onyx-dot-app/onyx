"use client";

import { useEffect, useState } from "react";
import { Button } from "@opal/components";
import { SvgMoon } from "@opal/icons";
import {
  useSession,
  useSessionId,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { useSandboxSleepWatcher } from "@/app/craft/hooks/useSandboxSleepWatcher";
import Modal from "@/refresh-components/Modal";

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
    <Modal open onOpenChange={(open) => !open && setDismissed(true)}>
      <Modal.Content width="sm" preventAccidentalClose={false}>
        <Modal.Header
          icon={SvgMoon}
          title="Your sandbox fell asleep"
          description="It went to sleep after a period of inactivity — your work is saved. Wake it to keep going."
        />
        <Modal.Footer justifyContent="center">
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
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
