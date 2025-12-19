"use client";

import { ValidStatuses } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/time";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiMinus,
  FiPauseCircle,
} from "react-icons/fi";
import {
  ConnectorCredentialPairStatus,
  PermissionSyncStatusEnum,
} from "@/app/admin/connector/[ccPairId]/types";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

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
        Failed
      </Badge>
    );
    if (errorMsg) {
      badge = (
        <SimpleTooltip tooltip={errorMsg}>
          <div className="cursor-pointer">{icon}</div>
        </SimpleTooltip>
      );
    } else {
      badge = icon;
    }
  } else if (status === "completed_with_errors") {
    badge = (
      <Badge variant="secondary" icon={FiAlertTriangle}>
        Completed with errors
      </Badge>
    );
  } else if (status === "success") {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        Succeeded
      </Badge>
    );
  } else if (status === "in_progress") {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        In Progress
      </Badge>
    );
  } else if (status === "not_started") {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        Scheduled
      </Badge>
    );
  } else if (status === "canceled") {
    badge = (
      <Badge variant="canceled" icon={FiClock}>
        Canceled
      </Badge>
    );
  } else if (status === "invalid") {
    badge = (
      <Badge variant="invalid" icon={FiAlertTriangle}>
        Invalid
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="outline" icon={FiMinus}>
        None
      </Badge>
    );
  }

  return <div>{badge}</div>;
}

export function PermissionSyncStatus({
  status,
  errorMsg,
}: {
  status: PermissionSyncStatusEnum | null;
  errorMsg?: string | null;
}) {
  let badge;

  if (status === PermissionSyncStatusEnum.FAILED) {
    const icon = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        Failed
      </Badge>
    );
    if (errorMsg) {
      badge = (
        <SimpleTooltip tooltip={errorMsg} side="bottom">
          <div className="cursor-pointer">{icon}</div>
        </SimpleTooltip>
      );
    } else {
      badge = icon;
    }
  } else if (status === PermissionSyncStatusEnum.COMPLETED_WITH_ERRORS) {
    badge = (
      <Badge variant="secondary" icon={FiAlertTriangle}>
        Completed with errors
      </Badge>
    );
  } else if (status === PermissionSyncStatusEnum.SUCCESS) {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        Succeeded
      </Badge>
    );
  } else if (status === PermissionSyncStatusEnum.IN_PROGRESS) {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        In Progress
      </Badge>
    );
  } else if (status === PermissionSyncStatusEnum.NOT_STARTED) {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        Scheduled
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="secondary" icon={FiClock}>
        Not Started
      </Badge>
    );
  }

  return <div>{badge}</div>;
}

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
  let badge;

  if (ccPairStatus == ConnectorCredentialPairStatus.DELETING) {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        Deleting
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.PAUSED) {
    badge = (
      <Badge variant="paused" icon={FiPauseCircle}>
        Paused
      </Badge>
    );
  } else if (inRepeatedErrorState) {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        Error
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.SCHEDULED) {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        Scheduled
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INITIAL_INDEXING) {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        Initial Indexing
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INVALID) {
    badge = (
      <Badge
        tooltip="Connector is in an invalid state. Please update the credentials or create a new connector."
        circle
        variant="invalid"
      >
        Invalid
      </Badge>
    );
  } else {
    if (lastIndexAttemptStatus && lastIndexAttemptStatus === "in_progress") {
      badge = (
        <Badge variant="in_progress" icon={FiClock}>
          Indexing
        </Badge>
      );
    } else if (
      lastIndexAttemptStatus &&
      lastIndexAttemptStatus === "canceled"
    ) {
      badge = (
        <Badge variant="canceled" icon={FiClock}>
          Canceled
        </Badge>
      );
    } else {
      badge = (
        <Badge variant="success" icon={FiCheckCircle}>
          Indexed
        </Badge>
      );
    }
  }

  return <div>{badge}</div>;
}
