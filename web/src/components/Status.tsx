"use client";
import i18n from "i18next";
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
  let badge;

  if (status === "failed") {
    const icon = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {i18n.t(k.FAILED)}
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
        {i18n.t(k.COMPLETED_WITH_ERRORS)}
      </Badge>
    );
  } else if (status === "success") {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        {i18n.t(k.SUCCEEDED)}
      </Badge>
    );
  } else if (status === "in_progress") {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        {i18n.t(k.IN_PROGRESS1)}
      </Badge>
    );
  } else if (status === "not_started") {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        {i18n.t(k.SCHEDULED)}
      </Badge>
    );
  } else if (status === "canceled") {
    badge = (
      <Badge variant="canceled" icon={FiClock}>
        {i18n.t(k.CANCELED)}
      </Badge>
    );
  } else if (status === "invalid") {
    badge = (
      <Badge variant="invalid" icon={FiAlertTriangle}>
        {i18n.t(k.INVALID)}
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="outline" icon={FiMinus}>
        {i18n.t(k.NONE)}
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
  let badge;

  if (ccPairStatus == ConnectorCredentialPairStatus.DELETING) {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {i18n.t(k.DELETING)}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.PAUSED) {
    badge = (
      <Badge variant="paused" icon={FiPauseCircle}>
        {i18n.t(k.PAUSED)}
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INVALID) {
    badge = (
      <Badge variant="invalid" icon={FiAlertTriangle}>
        {i18n.t(k.INVALID)}
      </Badge>
    );
  } else if (status === "failed") {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        {i18n.t(k.ERROR2)}
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        {i18n.t(k.ACTIVE)}
      </Badge>
    );
  }

  return <div>{badge}</div>;
}
