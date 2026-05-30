import { Text, View } from "react-native";

// OAuth redirect target. `onyx://callback?...` deep-links here; the token
// exchange that mints a PAT from the callback params is implemented in doc 07.
export default function Callback() {
  return (
    <View className="flex-1 items-center justify-center bg-background-neutral-00">
      <Text className="text-text-05 font-semibold">Signing in…</Text>
    </View>
  );
}
