import { Pressable } from "react-native";
import { router, type Href } from "expo-router";

import { cn } from "@/lib/utils";
import {
  ContentAction,
  type ContentActionProps,
} from "@/components/ui/content";

interface LineItemButtonProps extends ContentActionProps {
  onPress?: () => void;
  href?: Href;
  selected?: boolean;
  disabled?: boolean;
  className?: string;
}

// RN port of Opal `LineItemButton`: a tappable, full-width rounded row wrapping a
// `ContentAction`. Web's select-state foreground shift is approximated by a
// background change (touch has no hover); the hover Tooltip is dropped.
export function LineItemButton({
  onPress,
  href,
  selected = false,
  disabled = false,
  className,
  ...contentAction
}: LineItemButtonProps) {
  function handlePress() {
    onPress?.();
    if (href != null) router.navigate(href);
  }

  return (
    <Pressable
      disabled={disabled}
      onPress={handlePress}
      className={cn(
        "w-full rounded-08 p-8",
        selected && "bg-background-tint-00",
        !disabled && "active:bg-background-tint-03",
        disabled && "opacity-50",
        className,
      )}
    >
      <ContentAction {...contentAction} padding="fit" />
    </Pressable>
  );
}
