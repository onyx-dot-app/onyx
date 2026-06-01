import type { ReactNode } from "react";
import { View } from "react-native";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/cn";
import { Text, type TextColor } from "@/components/opal/Text";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TagTone = "neutral" | "info" | "success" | "warning" | "error";

// ---------------------------------------------------------------------------
// CVA — STATIC class strings (background + border per tone) for NativeWind.
// ---------------------------------------------------------------------------

const tagVariants = cva(
  "flex-row items-center self-start rounded-full border px-2 py-0.5",
  {
    variants: {
      tone: {
        neutral: "bg-background-neutral-02 border-border-01",
        info: "bg-status-info-01 border-status-info-02",
        success: "bg-status-success-01 border-status-success-02",
        warning: "bg-status-warning-01 border-status-warning-02",
        error: "bg-status-error-01 border-status-error-02",
      },
    },
    defaultVariants: {
      tone: "neutral",
    },
  },
);

// Label color token per tone — applied by `Text` via `style`.
const TAG_TEXT_COLOR: Record<TagTone, TextColor> = {
  neutral: "text-04",
  info: "status-text-info-05",
  success: "status-text-success-05",
  warning: "status-text-warning-05",
  error: "status-text-error-05",
};

// ---------------------------------------------------------------------------
// Tag
// ---------------------------------------------------------------------------

interface TagProps extends VariantProps<typeof tagVariants> {
  tone?: TagTone;
  className?: string;
  children?: ReactNode;
}

/**
 * Small pill / badge. Tone is a fixed small set, so styling uses CVA with
 * STATIC NativeWind classes; the label color is a token applied via `Text`
 * `style`.
 */
function Tag({ tone = "neutral", className, children }: TagProps) {
  return (
    <View className={cn(tagVariants({ tone }), className)}>
      {typeof children === "string" ? (
        <Text font="secondary-action" color={TAG_TEXT_COLOR[tone]}>
          {children}
        </Text>
      ) : (
        children
      )}
    </View>
  );
}

export { Tag, type TagProps };
