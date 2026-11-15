"use client";

import React from "react";
import { cn, richNodes } from "@opal/utils";
import { Text } from "@opal/components/text/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgLoader,
  SvgXOctagon,
} from "@opal/icons";

type MessageVariant =
  | "error"
  | "success"
  | "loading"
  | "warning"
  | "info"
  | "idle";

const iconMap: Record<MessageVariant, React.ReactNode> = {
  error: <SvgXOctagon className="h-3 w-3 stroke-status-error-05" />,
  success: <SvgCheckCircle className="h-3 w-3 stroke-status-success-05" />,
  loading: <SvgLoader className="h-3 w-3 stroke-text-02 animate-spin" />,
  warning: <SvgAlertCircle className="h-3 w-3 stroke-status-warning-05" />,
  info: <SvgAlertCircle className="h-3 w-3 stroke-text-03" />,
  idle: null,
};

interface FieldMessageRootProps extends React.HTMLAttributes<HTMLDivElement> {
  variant: MessageVariant;
  children: React.ReactNode;
}

const FieldMessageRoot: React.FC<FieldMessageRootProps> = ({
  variant,
  className,
  children,
  ...props
}) => {
  const icon = iconMap[variant];

  return (
    <div
      className={cn("flex flex-row items-center gap-x-0.5", className)}
      {...props}
    >
      {icon !== null && (
        <div className="w-4 h-4 flex items-center justify-center">{icon}</div>
      )}
      {children}
    </div>
  );
};

interface FieldMessageContentProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

// The layout classes sit on a wrapper because Opal's Text takes no className.
const FieldMessageContent: React.FC<FieldMessageContentProps> = ({
  className,
  children,
  ...props
}) => {
  return (
    <div className={cn("ms-0.5", className)} {...props}>
      <Text as="p" color="text-03" font="secondary-body">
        {richNodes(children)}
      </Text>
    </div>
  );
};

export const FieldMessage = Object.assign(FieldMessageRoot, {
  Content: FieldMessageContent,
});
