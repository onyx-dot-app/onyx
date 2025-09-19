"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../i18n/keys";

import { ValidStatuses } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiMinus,
  FiPauseCircle,
} from "react-icons/fi";
import { HoverPopup } from "./HoverPopup";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function IndexAttemptStatus({
  status,
  errorMsg,
}: {
  status: ValidStatuses | null;
  errorMsg?: string | null;
}) {
  const { t } = useTranslation();
  let badge;

  if (status === "failed") {
    const icon = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {t(k.FAILED)}
      </Badge>
    );

    if (errorMsg) {
      badge = (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="cursor-pointer">{icon}</div>
            </TooltipTrigger>
            <TooltipContent>{errorMsg}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      );
    } else {
      badge = icon;
    }
  } else if (status === "completed_with_errors") {
    badge = (
      <Badge variant="secondary" icon={FiAlertTriangle}>
        {t(k.COMPLETED_WITH_ERRORS)}
      </Badge>
    );
  } else if (status === "success") {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        {t(k.SUCCEEDED)}
      </Badge>
    );
  } else if (status === "in_progress") {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        {t(k.IN_PROGRESS1)}
      </Badge>
    );
  } else if (status === "not_started") {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        {t(k.SCHEDULED)}
      </Badge>
    );
  } else if (status === "canceled") {
    badge = (
      <Badge variant="canceled" icon={FiClock}>
        {t(k.CANCELED)}
      </Badge>
    );
  } else if (status === "invalid") {
    badge = (
      <Badge variant="invalid" icon={FiAlertTriangle}>
        {t(k.INVALID)}
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="outline" icon={FiMinus}>
        {t(k.NONE)}
      </Badge>
    );
  }

  return <div>{badge}</div>;
}

export function CCPairStatus({
  status,
  ccPairStatus,
  size = "md",
}: {
  status: ValidStatuses;
  ccPairStatus: ConnectorCredentialPairStatus;
  size?: "xs" | "sm" | "md" | "lg";
}) {
  const { t } = useTranslation();
  let badge;

  if (ccPairStatus == ConnectorCredentialPairStatus.DELETING) {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {t(k.DELETING)}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.PAUSED) {
    badge = (
      <Badge variant="paused" icon={FiPauseCircle}>
        {t(k.PAUSED)}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INVALID) {
    badge = (
      <Badge variant="invalid" icon={FiAlertTriangle}>
        {t(k.INVALID)}
      </Badge>
    );
  } else if (status === "failed") {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {t(k.ERROR2)}
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        {t(k.ACTIVE)}
      </Badge>
    );
  }

  return <div>{badge}</div>;
}
