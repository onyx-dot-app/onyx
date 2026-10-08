"use client";

import { type ReactElement, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, MessageCard, Modal, Text } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";
import { markdown } from "@opal/utils";
import { useOpenSearchResourceHealth } from "@/lib/opensearch-health/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  ResourceIssue,
  ResourceHealth,
  ResourcePopupResponse,
} from "@/lib/opensearch-health/types";
import { useUser } from "@/providers/UserProvider";
import { isAuthPath } from "@/lib/auth/paths";

const ISSUE_MESSAGE_KEYS: Record<
  ResourceIssue,
  {
    title: "diskTitle" | "jvmMemoryTitle" | "vectorMemoryTitle";
    description: "disk" | "jvmMemory" | "vectorMemory";
  }
> = {
  disk: { title: "diskTitle", description: "disk" },
  jvm_memory: { title: "jvmMemoryTitle", description: "jvmMemory" },
  vector_memory: { title: "vectorMemoryTitle", description: "vectorMemory" },
} as const;

interface ResourceDetailsProps {
  health: ResourceHealth;
}

function ResourceDetails({ health }: ResourceDetailsProps): ReactElement {
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

export function OpenSearchResourceBanner(): ReactElement | null {
  const t = useTranslations("opensearchHealth");
  const { user, isAdmin } = useUser();
  const { data, error } = useOpenSearchResourceHealth();
  const [detailsOpen, setDetailsOpen] = useState<boolean>(false);
  const hasIssues: boolean = !!data?.issues.length;
  useEffect(() => {
    setDetailsOpen(false);
  }, [user?.id, hasIssues]);
  if (!isAdmin || !data?.issues.length) return null;

  return (
    <div role="status" className="shrink-0 p-2">
      <MessageCard
        variant="warning"
        title={t("title")}
        rightChildren={
          <Button
            prominence="secondary"
            size="sm"
            onClick={() => setDetailsOpen(true)}
          >
            {t("viewDetails")}
          </Button>
        }
      />
      {detailsOpen && (
        <ResourceDialog
          health={{ ...data, stale: data.stale || !!error }}
          onClose={() => setDetailsOpen(false)}
        />
      )}
    </div>
  );
}

async function claimPopup(): Promise<ResourcePopupResponse> {
  const response: Response = await fetch(
    `${SWR_KEYS.opensearchResourceHealth}/popup`,
    {
      method: "POST",
    }
  );
  if (!response.ok)
    throw new Error("Unable to check OpenSearch resource warning");
  return response.json();
}

export function OpenSearchResourcePopup(): ReactElement | null {
  const pathname: string = usePathname();
  const { user, isAdmin } = useUser();
  // Login refreshes the user before redirecting; claim only after entering the app.
  const userId: string | undefined =
    isAdmin && !isAuthPath(pathname) ? user?.id : undefined;
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
    let active: boolean = true;
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
  return (
    <ResourceDialog health={warning.health} onClose={() => setWarning(null)} />
  );
}

interface ResourceDialogProps {
  health: ResourceHealth;
  onClose: () => void;
}

function ResourceDialog({
  health,
  onClose,
}: ResourceDialogProps): ReactElement {
  const t = useTranslations("opensearchHealth");
  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgAlertTriangle}
          title={t("title")}
          onClose={onClose}
        />
        <Modal.Body>
          <ResourceDetails health={health} />
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onClose}>{t("dismiss")}</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
