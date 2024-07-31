"use client";

import { ValidStatuses } from "@/lib/types";
import { Badge } from "@tremor/react";
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
  size = "md",
}: {
  status: ValidStatuses | null;
  errorMsg?: string | null;
  size?: "xs" | "sm" | "md" | "lg";
}) {
  let badge;

  if (status === "failed") {
    const icon = (
      <Badge size={size} color="red" icon={FiAlertTriangle}>
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
  } else if (status === "success") {
    badge = (
      <Badge size={size} color="green" icon={FiCheckCircle}>
        Succeeded
      </Badge>
    );
  } else if (status === "in_progress") {
    badge = (
      <Badge size={size} color="amber" icon={FiClock}>
        In Progress
      </Badge>
    );
  } else if (status === "not_started") {
    badge = (
      <Badge size={size} color="fuchsia" icon={FiClock}>
        Scheduled
      </Badge>
    );
  } else {
    badge = (
      <Badge size={size} color="gray" icon={FiMinus}>
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
      <Badge size={size} color="red" icon={FiAlertTriangle}>
        Deleting
      </Badge>
    );
  } else if (disabled) {
    badge = (
      <Badge size={size} color="yellow" icon={FiPauseCircle}>
        Paused
      </Badge>
    );
  } else if (status === "failed") {
    badge = (
      <Badge size={size} color="red" icon={FiAlertTriangle}>
        Error
      </Badge>
    );
  } else {
    badge = (
      <Badge size={size} color="green" icon={FiCheckCircle}>
        Active
      </Badge>
    );
  }

  return <div>{badge}</div>;
}
