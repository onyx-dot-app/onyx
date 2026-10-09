"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgMoon } from "@opal/icons";
import {
  useSession,
  useSessionId,
  useBuildSessionStore,
} from "@/app/craft/hooks/useBuildSessionStore";
import { Modal } from "@opal/components";

// Waking is always user-initiated — never automatic — so we don't keep pods
// alive forever and defeat idle reaping.
export default function SandboxAsleepNotice() {
  const t = useTranslations("craft.sandboxAsleep");
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
          title={t("modal.title")}
          description={t("modal.description")}
        />
        <Modal.Footer justifyContent="center">
          <Button
            variant="default"
            prominence="tertiary"
            onClick={() => setDismissed(true)}
          >
            {t("dismiss.button")}
          </Button>
          <Button variant="default" prominence="primary" onClick={handleWake}>
            {t("wake.button")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
