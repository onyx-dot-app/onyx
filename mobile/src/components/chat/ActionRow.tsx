import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { Text } from "@/components/opal";

interface ActionRowProps {
  icon: ReactNode;
  label: string;
  description: string;
  onPress: () => void;
}

export function ActionRow({ icon, label, description, onPress }: ActionRowProps) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      className="flex-row items-center gap-3 rounded-[8px] px-2 py-2 active:bg-background-tint-02"
    >
      <View className="h-5 w-5 items-center justify-center">{icon}</View>
      <View className="flex-1">
        <Text font="main-ui-body" color="text-05" numberOfLines={1}>
          {label}
        </Text>
        <Text font="secondary-body" color="text-03" numberOfLines={1}>
          {description}
        </Text>
      </View>
    </Pressable>
  );
}
