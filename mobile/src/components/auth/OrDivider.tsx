import { View } from "react-native";

import { Text } from "@/components/opal";

// The "or" divider between the Google button and the email/password form on the
// login and register screens: a thin rule on each side of a centered label.
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
