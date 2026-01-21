"use client";

import React, { useMemo } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgX,
  SvgXOctagon,
} from "@opal/icons";
const containerClasses = {
  flash: {
    default: {
      large: [
        "bg-background-neutral-00",
        "shadow-02",
        "rounded-16",
        "w-[40rem]",
      ],
      medium: [
        "bg-background-neutral-00",
        "shadow-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    info: {
      large: [
        "bg-status-info-00",
        "border",
        "border-status-info-05",
        "rounded-16",
        "w-[40rem]",
      ],
      medium: [
        "bg-status-info-00",
        "border",
        "border-status-info-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    success: {
      large: [
        "bg-status-success-00",
        "border",
        "border-status-success-05",
        "rounded-16",
        "w-[40rem]",
      ],
      medium: [
        "bg-status-success-00",
        "border",
        "border-status-success-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    warning: {
      large: [
        "bg-status-warning-00",
        "border",
        "border-status-warning-05",
        "rounded-16",
        "w-[40rem]",
      ],
      medium: [
        "bg-status-warning-00",
        "border",
        "border-status-warning-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    error: {
      large: [
        "bg-status-error-00",
        "border",
        "border-status-error-05",
        "rounded-16",
        "w-[40rem]",
      ],
      medium: [
        "bg-status-error-00",
        "border",
        "border-status-error-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
  },
  static: {
    default: {
      large: [
        "bg-background-tint-01",
        "border",
        "border-border-01",
        "rounded-16",
        "w-[19.375rem]",
      ],
      medium: [
        "bg-background-tint-01",
        "border",
        "border-border-01",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    info: {
      large: [
        "bg-status-info-00",
        "border",
        "border-status-info-02",
        "rounded-16",
        "w-[19.375rem]",
      ],
      medium: [
        "bg-status-info-00",
        "border",
        "border-status-info-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    success: {
      large: [
        "bg-status-success-00",
        "border",
        "border-status-success-02",
        "rounded-16",
        "w-[19.375rem]",
      ],
      medium: [
        "bg-status-success-00",
        "border",
        "border-status-success-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    warning: {
      large: [
        "bg-status-warning-00",
        "border",
        "border-status-warning-02",
        "rounded-16",
        "w-[19.375rem]",
      ],
      medium: [
        "bg-status-warning-00",
        "border",
        "border-status-warning-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
    error: {
      large: [
        "bg-status-error-00",
        "border",
        "border-status-error-02",
        "rounded-16",
        "w-[19.375rem]",
      ],
      medium: [
        "bg-status-error-00",
        "border",
        "border-status-error-02",
        "rounded-12",
        "w-[19.375rem]",
      ],
    },
  },
} as const;

const iconClasses = {
  default: "stroke-text-03",
  info: "stroke-status-info-05",
  success: "stroke-status-success-05",
  warning: "stroke-status-warning-05",
  error: "stroke-status-error-05",
} as const;

const textClasses = {
  flash: {
    text: "font-main-ui-action text-text-04",
    description: "font-secondary-body text-text-02",
  },
  static: {
    text: "font-main-ui-body text-text-04",
    description: "font-secondary-body text-text-02",
  },
} as const;

export interface MessageProps extends React.HTMLAttributes<HTMLDivElement> {
  // Type variants:
  flash?: boolean;
  static?: boolean;

  // Level variants:
  default?: boolean;
  info?: boolean;
  success?: boolean;
  warning?: boolean;
  error?: boolean;

  // Size variants:
  large?: boolean;
  medium?: boolean;

  // Content:
  text: string;
  description?: string;

  // Features:
  icon?: boolean;
  actions?: boolean | string;
  close?: boolean;

  // Callbacks:
  onClose?: () => void;
  onAction?: () => void;
}

function MessageInner(
  {
    flash,
    static: staticProp,

    default: defaultProp,
    info,
    success,
    warning,
    error,

    large,
    medium,

    text,
    description,

    icon = true,
    actions,
    close = true,

    onClose,
    onAction,

    className,
    ...props
  }: MessageProps,
  ref: React.ForwardedRef<HTMLDivElement>
) {
  const type = flash ? "flash" : staticProp ? "static" : "flash";
  const level = info
    ? "info"
    : success
      ? "success"
      : warning
        ? "warning"
        : error
          ? "error"
          : defaultProp
            ? "default"
            : "default";
  const size = large ? "large" : medium ? "medium" : "large";

  const containerClass = useMemo(
    () => containerClasses[type][level][size],
    [type, level, size]
  );

  const iconClass = useMemo(() => iconClasses[level], [level]);

  const textClass = useMemo(() => textClasses[type].text, [type]);
  const descriptionClass = useMemo(() => textClasses[type].description, [type]);

  const IconComponent =
    level === "success"
      ? SvgCheckCircle
      : level === "warning"
        ? SvgAlertTriangle
        : level === "error"
          ? SvgXOctagon
          : SvgAlertCircle;

  const contentPadding = size === "large" ? "p-2" : "p-1";
  const closeButtonSize =
    size === "large" ? "size-[2.25rem]" : "size-[1.75rem]";

  return (
    <div
      ref={ref}
      className={cn(
        "flex flex-row items-start gap-1 p-1",
        containerClass,
        className
      )}
      {...props}
    >
      {/* Content Container */}
      <div
        className={cn(
          "flex flex-1 flex-row items-start gap-1 min-w-0",
          contentPadding
        )}
      >
        {/* Icon Container */}
        {icon && (
          <div className="flex items-center justify-center p-0.5 size-[1.25rem] shrink-0">
            <IconComponent className={cn("size-[1rem]", iconClass)} />
          </div>
        )}

        {/* Text Content */}
        <div className="flex flex-col flex-1 items-start min-w-0 px-0.5">
          <Text as="p" className={cn("w-full", textClass)}>
            {text}
          </Text>
          {description && (
            <Text as="p" className={cn("w-full", descriptionClass)}>
              {description}
            </Text>
          )}
        </div>
      </div>

      {/* Actions */}
      {actions && (
        <div className="flex items-start justify-end shrink-0">
          <Button
            secondary
            onClick={onAction}
            className={size === "large" ? "p-2" : "p-1"}
          >
            {typeof actions === "string" ? actions : "Cancel"}
          </Button>
        </div>
      )}

      {/* Close Container */}
      {close && (
        <div className="flex items-center justify-center shrink-0">
          <div className={cn("flex items-start", closeButtonSize)}>
            <IconButton
              internal
              icon={SvgX}
              onClick={onClose}
              aria-label="Close"
              className={size === "large" ? "p-2 rounded-12" : "p-1 rounded-08"}
            />
          </div>
        </div>
      )}
    </div>
  );
}

const Message = React.forwardRef<HTMLDivElement, MessageProps>(MessageInner);
Message.displayName = "Message";

export default Message;
