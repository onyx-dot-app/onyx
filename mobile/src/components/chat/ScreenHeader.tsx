import type { ReactNode } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useDrawer } from "@/components/drawer/DrawerProvider";
import { SvgSidebar } from "@/components/icons/SvgSidebar";

// Shared header chrome (top inset + sidebar toggle); chat + project headers pass
// their title/actions as children.
export function ScreenHeader({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  const { toggle } = useDrawer();

  return (
    <View style={{ paddingTop: insets.top }} className="bg-background-neutral-00">
      <View className="h-12 flex-row items-center px-3">
        <Pressable
          onPress={toggle}
          hitSlop={10}
          accessibilityRole="button"
          accessibilityLabel="Open sidebar"
          className="rounded-[8px] p-1.5"
        >
          <SvgSidebar size={22} color="text-04" />
        </Pressable>

        {children}
      </View>
    </View>
  );
}
