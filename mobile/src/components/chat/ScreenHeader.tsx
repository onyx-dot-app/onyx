import type { ReactNode } from "react";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useDrawer } from "@/components/drawer/DrawerProvider";
import { SvgSidebar } from "@/components/icons/SvgSidebar";

// Shared screen-header chrome: the top inset, the fixed-height row, and the web
// SvgSidebar toggle that opens the drawer. The chat header and the project header
// both render this and supply their own title/actions as `children` (everything to
// the right of the sidebar toggle). Surface matches the web chat header
// (bg-background-neutral-00).
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
