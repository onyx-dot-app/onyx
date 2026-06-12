import { Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

// Home screen — styled with @onyx-ai/shared design tokens. The semantic classes
// (bg-background-neutral-*, text-text-*, rounded-12) resolve through the vars()
// provider in _layout.tsx, so colors flip with the system light/dark scheme exactly
// like web. Spacing/radius come from the shared token scale too.
export default function Home() {
  return (
    <SafeAreaView className="flex-1 bg-background-neutral-00">
      <View className="flex-1 items-center justify-center gap-2 px-6">
        <Text className="text-2xl font-semibold text-text-04">Onyx Mobile</Text>
        <Text className="text-center text-base text-text-03">
          Design tokens via @onyx-ai/shared — colors, spacing & radius, light &
          dark.
        </Text>
        <View className="mt-2 rounded-12 bg-background-neutral-02 px-4 py-2">
          <Text className="text-text-03">
            rounded-12 · background-neutral-02
          </Text>
        </View>
      </View>
    </SafeAreaView>
  );
}
