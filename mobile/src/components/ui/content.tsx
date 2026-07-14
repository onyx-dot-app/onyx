import type { ReactNode } from "react";
import { View } from "react-native";

import { cn } from "@/lib/utils";
import { Icon } from "@/components/ui/icon";
import { Text, type TextColor, type TextFont } from "@/components/ui/text";
import type { IconFunctionComponent } from "@/icons/types";

// RN port of Opal `Content` / `ContentAction` — minimal subset (ContentXl
// headline/section + ContentMd main-*). Unported layouts (Lg, Sm/body,
// editing, tag/aux, responsive grid) throw rather than render wrong.

type ContentSizePreset =
  | "headline"
  | "section"
  | "main-content"
  | "main-ui"
  | "secondary";
type ContentVariant = "heading" | "section" | "body";
type ContentColor = "default" | "muted" | "danger";

// web's data-content-color modes
const CONTENT_COLORS: Record<ContentColor, { title: TextColor; icon: string }> =
  {
    default: { title: "text-04", icon: "text-text-04" },
    muted: { title: "text-03", icon: "text-text-03" },
    danger: { title: "status-error-05", icon: "text-status-error-05" },
  };

// min-height = web line-height
const XL_PRESETS = {
  headline: {
    titleFont: "heading-h2",
    iconSize: 32,
    iconMinH: "min-h-36",
    iconRowMb: "",
  },
  section: {
    titleFont: "heading-h3",
    iconSize: 24,
    iconMinH: "min-h-28",
    iconRowMb: "mb-4",
  },
} as const satisfies Record<
  "headline" | "section",
  { titleFont: TextFont; iconSize: number; iconMinH: string; iconRowMb: string }
>;

// descIndent aligns the description under the title, past the icon
const MD_PRESETS = {
  "main-content": {
    titleFont: "main-content-emphasis",
    iconSize: 20,
    iconMinH: "min-h-24",
    descIndent: "pl-[26px]", // web 1.625rem
  },
  "main-ui": {
    titleFont: "main-ui-action",
    iconSize: 16,
    iconMinH: "min-h-20",
    descIndent: "pl-[22px]", // web 1.375rem
  },
  secondary: {
    titleFont: "secondary-action",
    iconSize: 12,
    iconMinH: "min-h-16",
    descIndent: "pl-[18px]", // web 1.125rem
  },
} as const satisfies Record<
  "main-content" | "main-ui" | "secondary",
  {
    titleFont: TextFont;
    iconSize: number;
    iconMinH: string;
    descIndent: string;
  }
>;

interface ContentProps {
  icon?: IconFunctionComponent;
  // custom leading element (e.g. AgentAvatar); wins over `icon`
  leading?: ReactNode;
  title: string;
  description?: string;
  titleMaxLines?: number;
  descriptionMaxLines?: number;
  color?: ContentColor;
  sizePreset?: ContentSizePreset;
  variant?: ContentVariant;
  className?: string;
}

function Content({
  icon,
  leading,
  title,
  description,
  titleMaxLines,
  descriptionMaxLines,
  color = "default",
  sizePreset = "headline",
  variant = "heading",
  className,
}: ContentProps) {
  const colors = CONTENT_COLORS[color];

  if (
    (sizePreset === "headline" || sizePreset === "section") &&
    variant === "heading"
  ) {
    const preset = XL_PRESETS[sizePreset];
    return (
      <View className={cn("flex-col items-start", className)}>
        {leading ? (
          <View className={cn("flex-row items-center gap-4", preset.iconRowMb)}>
            <View className="shrink-0 items-center justify-center">
              {leading}
            </View>
          </View>
        ) : icon ? (
          <View className={cn("flex-row items-center gap-4", preset.iconRowMb)}>
            <View
              className={cn("items-center justify-center p-2", preset.iconMinH)}
            >
              <Icon as={icon} size={preset.iconSize} className={colors.icon} />
            </View>
          </View>
        ) : null}
        <View className="w-full flex-row items-center gap-4">
          <Text
            font={preset.titleFont}
            color={colors.title}
            maxLines={titleMaxLines}
            className="flex-1"
          >
            {title}
          </Text>
        </View>
        {description ? (
          <Text
            font="secondary-body"
            color="text-03"
            maxLines={descriptionMaxLines}
            className="w-full"
          >
            {description}
          </Text>
        ) : null}
      </View>
    );
  }

  if (
    sizePreset === "main-content" ||
    sizePreset === "main-ui" ||
    sizePreset === "secondary"
  ) {
    if (variant === "body") {
      throw new Error("Content: 'body' variant (ContentSm) is not ported");
    }
    const preset = MD_PRESETS[sizePreset];
    return (
      <View className={cn("flex-col items-start", className)}>
        <View className="w-full flex-row items-center gap-2">
          {leading ? (
            <View className="shrink-0 items-center justify-center">
              {leading}
            </View>
          ) : icon ? (
            <View
              className={cn("items-center justify-center p-2", preset.iconMinH)}
            >
              <Icon as={icon} size={preset.iconSize} className={colors.icon} />
            </View>
          ) : null}
          <Text
            font={preset.titleFont}
            color={colors.title}
            maxLines={titleMaxLines}
            className="flex-1"
          >
            {title}
          </Text>
        </View>
        {description ? (
          <Text
            font="secondary-body"
            color="text-03"
            maxLines={descriptionMaxLines}
            className={cn("w-full", (icon || leading) && preset.descIndent)}
          >
            {description}
          </Text>
        ) : null}
      </View>
    );
  }

  throw new Error(
    `Content: unsupported sizePreset="${sizePreset}" variant="${variant}" (only headline/section+heading and main-*+section/heading are ported)`,
  );
}

type ContentPadding = "fit" | "sm" | "md" | "lg";

// web p-0/p-1/p-1/p-2 → mobile px
const ACTION_PADDING: Record<ContentPadding, string> = {
  fit: "p-0",
  sm: "p-4",
  md: "p-4",
  lg: "p-8",
};

interface ContentActionProps extends ContentProps {
  rightChildren?: ReactNode;
  padding?: ContentPadding;
  center?: boolean;
}

// Content + right-side actions (mirrors web ContentAction; no responsive mode).
function ContentAction({
  rightChildren,
  padding = "lg",
  center = false,
  ...content
}: ContentActionProps) {
  return (
    <View
      className={cn(
        "w-full flex-row gap-16",
        center ? "items-center" : "items-stretch",
      )}
    >
      <View
        className={cn(
          "min-w-0 flex-1",
          center ? "self-center" : "self-start",
          ACTION_PADDING[padding],
        )}
      >
        <Content {...content} />
      </View>
      {rightChildren ? (
        <View
          className={cn(
            "shrink-0 flex-row",
            center ? "items-center" : "items-stretch",
          )}
        >
          {rightChildren}
        </View>
      ) : null}
    </View>
  );
}

export {
  Content,
  ContentAction,
  type ContentProps,
  type ContentActionProps,
  type ContentSizePreset,
  type ContentVariant,
  type ContentColor,
};
