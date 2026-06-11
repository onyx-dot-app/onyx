import { Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

// Placeholder home screen. Design system (tokens/theme) arrives via @onyx-ai/shared later.
export default function Home() {
  return (
    <SafeAreaView className="flex-1 bg-white">
      <View className="flex-1 items-center justify-center gap-2 px-6">
        <Text className="text-2xl font-semibold text-neutral-900">
          Onyx Mobile
        </Text>
        <Text className="text-center text-base text-neutral-500">
          Scaffold ready — Expo SDK 56 · Expo Router · NativeWind v4.
        </Text>
      </View>
    </SafeAreaView>
  );
}
