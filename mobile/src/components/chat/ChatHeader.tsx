import { Pressable, View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import { useSidebar } from "@/components/sidebar";
import SvgSidebar from "@/icons/sidebar";

interface ChatHeaderProps {
  title?: string;
}

// Slim top bar: sidebar trigger + optional session title (mobile's entry into
// the sidebar-centric nav).
export function ChatHeader({ title }: ChatHeaderProps) {
  const { setFolded } = useSidebar();

  return (
    <View className="flex-row items-center gap-2 px-4 py-3">
      <Pressable
        onPress={() => setFolded(false)}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel="Open sidebar"
        className="rounded-08 p-2 active:bg-background-tint-03"
      >
        <Icon as={SvgSidebar} size={24} className="text-text-04" />
      </Pressable>
      {title ? (
        <Text font="main-ui-action" numberOfLines={1} className="flex-1">
          {title}
        </Text>
      ) : null}
    </View>
  );
}
