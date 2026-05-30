import { Link, Stack } from "expo-router";
import { Text, View } from "react-native";

// Fallback route for unmatched paths.
export default function NotFound() {
  return (
    <>
      <Stack.Screen options={{ title: "Not found" }} />
      <View className="flex-1 items-center justify-center gap-2 bg-background-neutral-00">
        <Text className="text-text-05 font-semibold">This screen does not exist.</Text>
        <Link href={"/" as never} className="text-action-link-05">
          Go home
        </Link>
      </View>
    </>
  );
}
