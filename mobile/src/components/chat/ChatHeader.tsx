import { View } from "react-native";

import { Button } from "@/components/ui/button";
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
    <View className="flex-row items-center gap-2 px-4 py-12">
      <Button
        prominence="internal"
        icon={SvgSidebar}
        accessibilityLabel="Open sidebar"
        onPress={() => setFolded(false)}
      />
      {title ? (
        <Text font="main-ui-action" numberOfLines={1} className="flex-1">
          {title}
        </Text>
      ) : null}
    </View>
  );
}
