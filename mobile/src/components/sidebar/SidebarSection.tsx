import { type ReactNode } from "react";
import { View } from "react-native";

import { Text } from "@/components/opal";

// A labelled sidebar section (web: SidebarSection).
export function SidebarSection({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <View>
      <View className="min-h-8 justify-center pl-4 pr-2 py-1">
        <Text font="secondary-body" color="text-02">
          {title}
        </Text>
      </View>
      {children}
    </View>
  );
}
