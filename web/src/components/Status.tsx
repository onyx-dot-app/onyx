"use client";

import { useTranslations } from "next-intl";
import { ValidStatuses } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiPauseCircle,
} from "react-icons/fi";
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";

export function CCPairStatus({
  ccPairStatus,
  inRepeatedErrorState,
  lastIndexAttemptStatus,
  size = "md",
}: {
  ccPairStatus: ConnectorCredentialPairStatus;
  inRepeatedErrorState: boolean;
  lastIndexAttemptStatus: ValidStatuses | undefined | null;
  size?: "xs" | "sm" | "md" | "lg";
}) {
  const t = useTranslations("admin.status.badges");
  let badge;

  if (ccPairStatus == ConnectorCredentialPairStatus.DELETING) {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {t("deleting")}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.PAUSED) {
    badge = (
      <Badge variant="paused" icon={FiPauseCircle}>
        {t("paused")}
      </Badge>
    );
  } else if (inRepeatedErrorState && lastIndexAttemptStatus !== "in_progress") {
    // A live attempt reads as "Indexing". The sticky error state only shows
    // once that attempt is no longer running.
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {t("error")}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.SCHEDULED) {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        {t("scheduled")}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INITIAL_INDEXING) {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        {t("initialIndexing")}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INVALID) {
    badge = (
      <Badge tooltip={t("invalidConnectorTooltip")} circle variant="invalid">
        {t("invalid")}
      </Badge>
    );
  } else {
    if (lastIndexAttemptStatus && lastIndexAttemptStatus === "in_progress") {
      badge = (
        <Badge variant="in_progress" icon={FiClock}>
          {t("indexing")}
        </Badge>
      );
    } else if (
      lastIndexAttemptStatus &&
      lastIndexAttemptStatus === "not_started"
    ) {
      badge = (
        <Badge variant="not_started" icon={FiClock}>
          {t("scheduled")}
        </Badge>
      );
    } else if (
      lastIndexAttemptStatus &&
      lastIndexAttemptStatus === "canceled"
    ) {
      badge = (
        <Badge variant="canceled" icon={FiClock}>
          {t("canceled")}
        </Badge>
      );
    } else if (lastIndexAttemptStatus === "interrupted") {
      // resumes automatically, so it's neutral rather than the green "Indexed"
      badge = (
        <Badge variant="canceled" icon={FiClock}>
          {t("interrupted")}
        </Badge>
      );
    } else {
      badge = (
        <Badge variant="success" icon={FiCheckCircle}>
          {t("indexed")}
        </Badge>
      );
    }
  }

  return <div>{badge}</div>;
}
