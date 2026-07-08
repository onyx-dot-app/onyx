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

// RN port of Opal LineItemButton. No hover tooltip; select state shows as a background change.
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
        "w-full rounded-12 p-8",
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
