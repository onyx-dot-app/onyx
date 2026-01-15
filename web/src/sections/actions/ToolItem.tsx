"use client";

import React, { useMemo } from "react";
import { cn } from "@/lib/utils";
import Switch from "@/refresh-components/inputs/Switch";
import Text from "@/refresh-components/texts/Text";
import Truncated from "@/refresh-components/texts/Truncated";
import type { IconProps } from "@opal/types";
import {
  SvgAlertTriangle,
  SvgArrowLeftDot,
  SvgArrowRightDot,
  SvgCornerRightUpDot,
  SvgMinusCircle,
} from "@opal/icons";

type ToolItemVariant = "mcp" | "openapi";

interface OpenApiMetadata {
  method?: string;
  path?: string;
}

const METHOD_ICON_MAP: Record<string, React.ReactNode> = {
  GET: <SvgArrowLeftDot className="size-4 stroke-status-success-05" />,
  POST: <SvgArrowRightDot className="size-4 stroke-status-info-05" />,
  PUT: <SvgCornerRightUpDot className="size-4 stroke-status-info-05" />,
  PATCH: <SvgCornerRightUpDot className="size-4 stroke-status-warning-05" />,
  DELETE: <SvgMinusCircle className="size-4 stroke-status-error-05" />,
};
const METHOD_STYLE_MAP: Record<string, { bg: string; text: string }> = {
  GET: { bg: "bg-status-success-00", text: "text-status-success-05" },
  POST: { bg: "bg-status-info-00", text: "text-status-info-05" },
  PUT: { bg: "bg-status-info-00", text: "text-status-info-05" },
  PATCH: { bg: "bg-status-warning-00", text: "text-status-warning-05" },
  DELETE: { bg: "bg-status-error-00", text: "text-status-error-05" },
};

function getMethodStyles(method?: string) {
  if (!method) {
    return {
      label: undefined,
      bg: "bg-background-neutral-01",
      text: "text-text-03",
    };
  }

  const upperMethod = method.toUpperCase();
  const styles = METHOD_STYLE_MAP[upperMethod] ?? {
    bg: "bg-background-neutral-01",
    text: "text-text-03",
  };

  return {
    label: upperMethod,
    ...styles,
  };
}

export interface ToolItemProps {
  // Tool information
  name: string;
  description: string;
  icon?: React.FunctionComponent<IconProps>;

  // Tool state
  isAvailable?: boolean;
  isEnabled?: boolean;

  // Variant
  variant?: ToolItemVariant;
  openApiMetadata?: OpenApiMetadata;

  // Handlers
  onToggle?: (enabled: boolean) => void;

  // Optional styling
  className?: string;
}

const ToolItem: React.FC<ToolItemProps> = ({
  name,
  description,
  icon: Icon,
  isAvailable = true,
  isEnabled = true,
  variant = "mcp",
  openApiMetadata,
  onToggle,
  className,
}) => {
  const isMcpVariant = variant === "mcp";

  const unavailableStyles =
    isMcpVariant && !isAvailable
      ? "bg-background-neutral-02"
      : "bg-background-tint-00";

  const textOpacity = isMcpVariant && !isAvailable ? "opacity-50" : "";

  const {
    label: methodLabel,
    bg: methodBg,
    text: methodText,
  } = isMcpVariant
    ? { label: undefined, bg: "", text: "" }
    : getMethodStyles(openApiMetadata?.method);

  const highlightedPathContent = useMemo(() => {
    if (!openApiMetadata?.path) {
      return null;
    }

    // Example: "/repos/{owner}/{repo}" => plain spans for static segments,
    // colored spans for "{owner}" and "{repo}".
    const path = openApiMetadata.path;
    const segments: React.ReactNode[] = [];
    const paramRegex = /\{[^}]+\}/g;
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    const highlightClass = methodText || "text-text-03";

    while ((match = paramRegex.exec(path)) !== null) {
      // Push plain text before the param, then the colored "{param}" segment.
      if (match.index > lastIndex) {
        segments.push(
          <span key={`text-${match.index}`}>
            {path.slice(lastIndex, match.index)}
          </span>
        );
      }

      segments.push(
        <span key={`param-${match.index}`} className={highlightClass}>
          {match[0]}
        </span>
      );

      lastIndex = paramRegex.lastIndex;
    }

    if (lastIndex < path.length) {
      segments.push(<span key="text-end">{path.slice(lastIndex)}</span>);
    }

    return segments;
  }, [openApiMetadata?.path, methodText]);

  return (
    <div
      className={cn(
        "flex items-start justify-between w-full p-2 rounded-08 border border-border-01 gap-2",
        unavailableStyles,
        className
      )}
    >
      {/* Left Section: Icon and Content */}
      <div className="flex gap-1 items-start flex-1 min-w-0 pr-2">
        {/* Icon Container */}
        {Icon ? (
          <div
            className={cn(
              "flex items-center justify-center shrink-0",
              textOpacity
            )}
          >
            <Icon size={20} className="h-5 w-5 stroke-text-04" />
          </div>
        ) : (
          <div className="flex items-center justify-center h-5 w-5">
            {METHOD_ICON_MAP[openApiMetadata?.method?.toUpperCase() ?? ""]}
          </div>
        )}

        {/* Content Container */}
        <div className="flex flex-col items-start flex-1 min-w-0">
          {/* Tool Name */}
          <div className="flex items-center w-full min-h-[20px] px-0.5">
            <Truncated
              mainUiAction
              text04
              className={cn(
                "truncate",
                textOpacity,
                !isAvailable && "line-through"
              )}
            >
              {name}
            </Truncated>
          </div>

          {/* Description */}
          <div className="px-0.5 w-full">
            <Truncated
              text03
              secondaryBody
              className={cn("whitespace-pre-wrap", textOpacity)}
            >
              {description}
            </Truncated>
          </div>
        </div>
      </div>

      {/* Right Section */}
      {isMcpVariant ? (
        <div className="flex gap-2 items-start justify-end shrink-0">
          {/* Unavailable Badge */}
          {!isAvailable && (
            <div className="flex items-center min-h-[20px] px-0 py-0.5">
              <div className="flex gap-0.5 items-center">
                <div className="flex items-center px-0.5">
                  <Text as="p" text03 secondaryBody className="text-right">
                    Tool unavailable
                  </Text>
                </div>
                <div className="flex items-center justify-center p-0.5 w-4 h-4">
                  <SvgAlertTriangle className="w-3 h-3 stroke-status-warning-05" />
                </div>
              </div>
            </div>
          )}

          {/* Switch */}
          <div className="flex items-center justify-center gap-1 h-5 px-0.5 py-0.5">
            <Switch
              checked={isEnabled}
              onCheckedChange={onToggle}
              disabled={!isAvailable}
              aria-label={`tool-toggle-${name}`}
            />
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-end justify-center">
          {methodLabel && (
            <div
              className={cn("rounded-04 border border-transparent", methodBg)}
            >
              <Text
                as="p"
                figureSmallLabel
                className={cn("uppercase tracking-wide p-0.5 ", methodText)}
              >
                {methodLabel}
              </Text>
            </div>
          )}

          {openApiMetadata?.path && (
            <Truncated secondaryMono text03 className="text-right truncate">
              {highlightedPathContent}
            </Truncated>
          )}
        </div>
      )}
    </div>
  );
};

ToolItem.displayName = "ToolItem";
export default ToolItem;
