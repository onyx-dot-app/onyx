"use client";

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
        <HoverPopup
          mainContent={<div className="cursor-pointer">{icon}</div>}
          popupContent={
            <div className="w-64 p-2 break-words overflow-hidden whitespace-normal">
              {errorMsg}
            </div>
          }
        />
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
  } else {
    badge = (
      <Badge variant="outline" icon={FiMinus}>
        None
      </Badge>
    );
  }

  return <div>{badge}</div>;
}

export function CCPairStatus({
  status,
  disabled,
  isDeleting,
  size = "md",
}: {
  status: ValidStatuses;
  disabled: boolean;
  isDeleting: boolean;
  size?: "xs" | "sm" | "md" | "lg";
}) {
  let badge;

  if (isDeleting) {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        Deleting
      </Badge>
    );
  } else if (disabled) {
    badge = (
      <Badge variant="paused" icon={FiPauseCircle}>
        Paused
      </Badge>
    );
  } else if (status === "failed") {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        Error
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        Active
      </Badge>
    );
  }

  return <div>{badge}</div>;
}
