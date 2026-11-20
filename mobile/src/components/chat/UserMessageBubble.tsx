import { View } from "react-native";

import { Text } from "@/components/ui/text";

// Web HumanMessage bubble: squared bottom-right corner.
export function UserMessageBubble({ text }: { text: string }) {
  return (
    <View className="max-w-[85%] rounded-t-16 rounded-bl-16 bg-background-tint-02 px-12 py-8">
      {/* 14px body: deliberate reduction from web's 16px, which reads oversized on a phone. */}
      <Text font="main-ui-body" color="text-05">
        {text}
      </Text>
    </View>
  );
}
