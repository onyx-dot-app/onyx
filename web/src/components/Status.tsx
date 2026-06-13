"use client";

import { ValidStatuses } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@opal/time";
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
import { Tooltip } from "@opal/components";

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
        失败
      </Badge>
    );
    if (errorMsg) {
      badge = (
        <Tooltip tooltip={errorMsg}>
          <div className="cursor-pointer">{icon}</div>
        </Tooltip>
      );
    } else {
      badge = icon;
    }
  } else if (status === "completed_with_errors") {
    badge = (
      <Badge variant="secondary" icon={FiAlertTriangle}>
        已完成但有错误
      </Badge>
    );
  } else if (status === "success") {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        成功
      </Badge>
    );
  } else if (status === "in_progress") {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        进行中
      </Badge>
    );
  } else if (status === "not_started") {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        已安排
      </Badge>
    );
  } else if (status === "canceled") {
    badge = (
      <Badge variant="canceled" icon={FiClock}>
        已取消
      </Badge>
    );
  } else if (status === "invalid") {
    badge = (
      <Badge variant="invalid" icon={FiAlertTriangle}>
        无效
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="outline" icon={FiMinus}>
        无
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
        失败
      </Badge>
    );
    if (errorMsg) {
      badge = (
        <Tooltip tooltip={errorMsg} side="bottom">
          <div className="cursor-pointer">{icon}</div>
        </Tooltip>
      );
    } else {
      badge = icon;
    }
  } else if (status === PermissionSyncStatusEnum.COMPLETED_WITH_ERRORS) {
    badge = (
      <Badge variant="secondary" icon={FiAlertTriangle}>
        已完成但有错误
      </Badge>
    );
  } else if (status === PermissionSyncStatusEnum.SUCCESS) {
    badge = (
      <Badge variant="success" icon={FiCheckCircle}>
        成功
      </Badge>
    );
  } else if (status === PermissionSyncStatusEnum.IN_PROGRESS) {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        进行中
      </Badge>
    );
  } else if (status === PermissionSyncStatusEnum.NOT_STARTED) {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        已安排
      </Badge>
    );
  } else {
    badge = (
      <Badge variant="secondary" icon={FiClock}>
        未开始
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
        正在删除
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.PAUSED) {
    badge = (
      <Badge variant="paused" icon={FiPauseCircle}>
        已暂停
      </Badge>
    );
  } else if (inRepeatedErrorState) {
    badge = (
      <Badge variant="destructive" icon={FiAlertTriangle}>
        错误
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.SCHEDULED) {
    badge = (
      <Badge variant="not_started" icon={FiClock}>
        已安排
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INITIAL_INDEXING) {
    badge = (
      <Badge variant="in_progress" icon={FiClock}>
        初始索引中
      </Badge>
    );
  } else if (ccPairStatus == ConnectorCredentialPairStatus.INVALID) {
    badge = (
      <Badge
        tooltip="连接器处于无效状态。请更新凭据或创建新的连接器。"
        circle
        variant="invalid"
      >
        无效
      </Badge>
    );
  } else {
    if (lastIndexAttemptStatus && lastIndexAttemptStatus === "in_progress") {
      badge = (
        <Badge variant="in_progress" icon={FiClock}>
          索引中
        </Badge>
      );
    } else if (
      lastIndexAttemptStatus &&
      lastIndexAttemptStatus === "not_started"
    ) {
      badge = (
        <Badge variant="not_started" icon={FiClock}>
          已安排
        </Badge>
      );
    } else if (
      lastIndexAttemptStatus &&
      lastIndexAttemptStatus === "canceled"
    ) {
      badge = (
        <Badge variant="canceled" icon={FiClock}>
          已取消
        </Badge>
      );
    } else {
      badge = (
        <Badge variant="success" icon={FiCheckCircle}>
          已索引
        </Badge>
      );
    }
  }

  return <div>{badge}</div>;
}
