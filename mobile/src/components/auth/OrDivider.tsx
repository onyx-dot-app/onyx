import { View } from "react-native";

import { Text } from "@/components/opal";

export function OrDivider() {
  return (
    <View className="flex-row items-center gap-2">
      <View className="h-[1px] flex-1 bg-border-01" />
      <Text font="secondary-body" color="text-03">
        or
      </Text>
      <View className="h-[1px] flex-1 bg-border-01" />
    </View>
  );
}
