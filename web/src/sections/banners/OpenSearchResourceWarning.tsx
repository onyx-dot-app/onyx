"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, MessageCard, Modal, Text } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";
import { markdown } from "@opal/utils";
import {
  RESOURCE_HEALTH_URL,
  useOpenSearchResourceHealth,
} from "@/lib/opensearch-health/hooks";
import {
  ResourceHealth,
  ResourcePopupResponse,
} from "@/lib/opensearch-health/types";
import { useUser } from "@/providers/UserProvider";
import { isAuthPath } from "@/lib/auth/paths";

const ISSUE_MESSAGE_KEYS = {
  disk: { title: "diskTitle", description: "disk" },
  jvm_memory: { title: "jvmMemoryTitle", description: "jvmMemory" },
  vector_memory: { title: "vectorMemoryTitle", description: "vectorMemory" },
} as const;

function ResourceDetails({ health }: { health: ResourceHealth }) {
  const t = useTranslations("opensearchHealth");
  return (
    <div className="flex flex-col gap-4">
      <ol
        className={
          health.issues.length > 1
            ? "space-y-3 list-decimal ps-5 marker:font-semibold marker:text-text-03"
            : "list-none"
        }
      >
        {health.issues.map((issue) => (
          <li key={issue}>
            <div className="flex flex-col gap-1">
              <Text as="p" font="main-ui-action">
                {t(ISSUE_MESSAGE_KEYS[issue].title)}
              </Text>
              <Text as="p" font="main-ui-muted" color="text-03">
                {t(ISSUE_MESSAGE_KEYS[issue].description)}
              </Text>
            </div>
          </li>
        ))}
      </ol>
      <div className="flex flex-col gap-2 border-t border-border-01 pt-3">
        <Text as="p">{markdown(t("contact"))}</Text>
        {health.stale && (
          <Text as="p" font="secondary-body" color="text-03">
            {t("stale")}
          </Text>
        )}
      </div>
    </div>
  );
}

export function OpenSearchResourceBanner() {
  const t = useTranslations("opensearchHealth");
  const { isAdmin } = useUser();
  const { data, error } = useOpenSearchResourceHealth();
  if (!isAdmin || !data?.issues.length) return null;

  return (
    <div role="status" className="shrink-0 p-2">
      <MessageCard
        variant="warning"
        title={t("title")}
        bottomChildren={
          <ResourceDetails health={{ ...data, stale: data.stale || !!error }} />
        }
      />
    </div>
  );
}

async function claimPopup(): Promise<ResourcePopupResponse> {
  const response = await fetch(`${RESOURCE_HEALTH_URL}/popup`, {
    method: "POST",
  });
  if (!response.ok)
    throw new Error("Unable to check OpenSearch resource warning");
  return response.json();
}

export function OpenSearchResourcePopup() {
  const t = useTranslations("opensearchHealth");
  const pathname = usePathname();
  const { user, isAdmin } = useUser();
  // Login refreshes the user before redirecting; claim only after entering the app.
  const userId = isAdmin && !isAuthPath(pathname) ? user?.id : undefined;
  const [warning, setWarning] = useState<{
    userId: string;
    health: ResourceHealth;
  } | null>(null);
  const request = useRef<{
    userId: string;
    result: Promise<ResourcePopupResponse>;
  } | null>(null);

  useEffect(() => {
    setWarning(null);
    if (!userId) {
      request.current = null;
      return;
    }
    // One attempt per entry; reuse the promise through React's effect replay.
    if (request.current?.userId !== userId) {
      request.current = { userId, result: claimPopup() };
    }
    let active = true;
    request.current.result
      .then((response) => {
        if (active && response.show_popup) {
          setWarning({ userId, health: response.health });
        }
      })
      .catch((error: unknown) => {
        console.error("OpenSearch resource warning unavailable", error);
      });
    return () => {
      active = false;
    };
  }, [userId]);

  if (!warning || warning.userId !== userId) return null;
  const close = () => setWarning(null);
  return (
    <Modal open onOpenChange={close}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgAlertTriangle}
          title={t("title")}
          onClose={close}
        />
        <Modal.Body>
          <ResourceDetails health={warning.health} />
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={close}>{t("dismiss")}</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
