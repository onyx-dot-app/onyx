import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Text } from "@/components/opal";
import { useToken } from "@/theme/ThemeProvider";
import { useDrawer } from "@/components/drawer/DrawerProvider";
import { ChevronDownIcon, SidebarIcon } from "@/components/ui/icons";

// Chat-screen header: the web SvgSidebar toggle (opens the drawer) + a static
// "Chat" title with a decorative chevron. Surface matches the web chat header
// (bg-background-neutral-00). The selector behind the chevron is a later phase.
export function ChatHeader() {
  const insets = useSafeAreaInsets();
  const { toggle } = useDrawer();
  const iconColor = useToken("text-04");
  const chevronColor = useToken("text-03");

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
          <SidebarIcon size={22} color={iconColor} />
        </Pressable>

        <View className="ml-2 flex-row items-center gap-1">
          <Text font="main-ui-action" color="text-05">
            Chat
          </Text>
          <ChevronDownIcon size={16} color={chevronColor} />
        </View>
      </View>
    </View>
  );
}
