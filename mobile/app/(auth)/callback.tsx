import { View } from "react-native";
import { Redirect } from "expo-router";

import { useAuth } from "@/auth";
import { Text } from "@/components/opal";

// OAuth redirect target for the COLD-START path: launching the app via
// onyx://callback#token=<JWT> (or ?token=) mounts this. AuthProvider reads the
// launch URL on mount and adopts the JWT, so here we just reflect the resolved
// status. (The warm path resolves inside loginWithGoogle and never mounts this.)
export default function Callback() {
  const { status } = useAuth();

  if (status === "signedIn") {
    return <Redirect href={"/(app)/(chat)" as never} />;
  }
  if (status === "signedOut") {
    return <Redirect href={"/(auth)/login" as never} />;
  }
  return (
    <View className="flex-1 items-center justify-center bg-background-neutral-00">
      <Text font="main-ui-body" color="text-03">
        Signing in…
      </Text>
    </View>
  );
}
