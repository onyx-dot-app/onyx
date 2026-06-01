import { View } from "react-native";

import { Text } from "@/components/opal";
import { SvgChevronDown } from "@/components/icons/SvgChevronDown";
import { ScreenHeader } from "@/components/chat/ScreenHeader";

// Chat-screen header: the shared ScreenHeader chrome (web SvgSidebar toggle that
// opens the drawer) + a static "Chat" title with a decorative chevron.
export function ChatHeader() {
  return (
    <ScreenHeader>
      <View className="ml-2 flex-row items-center gap-1">
        <Text font="main-ui-action" color="text-05">
          Chat
        </Text>
        <SvgChevronDown size={16} color="text-03" />
      </View>
    </ScreenHeader>
  );
}
