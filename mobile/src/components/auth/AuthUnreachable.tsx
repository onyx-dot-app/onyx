// Self-clears: the `/api/me` query refetches on app focus / reconnect once the instance is reachable.
import { router } from "expo-router";
import { View } from "react-native";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Text } from "@/components/ui/text";
import SvgAlertCircle from "@/icons/alert-circle";

interface AuthUnreachableProps {
  onRetry: () => void;
  retrying: boolean;
}

export function AuthUnreachable({ onRetry, retrying }: AuthUnreachableProps) {
  return (
    <View
      accessibilityViewIsModal
      className="absolute inset-0 justify-center bg-background-neutral-00 px-24"
    >
      <View className="items-center">
        <Icon as={SvgAlertCircle} size={44} className="text-status-error-05" />
        <Text font="heading-h3" color="text-05" className="mt-16 text-center">
          Can&apos;t reach your Onyx instance
        </Text>
        <Text font="main-ui-muted" color="text-03" className="mt-4 text-center">
          Make sure the server is running and reachable, then try again.
        </Text>
      </View>

      <View className="mt-24">
        <Button width="full" loading={retrying} onPress={onRetry}>
          {retrying ? "Retrying…" : "Try Again"}
        </Button>
        <View className="mt-12">
          <Button
            width="full"
            variant="action"
            prominence="tertiary"
            onPress={() => router.replace("/(auth)/connect")}
          >
            Change instance
          </Button>
        </View>
      </View>
    </View>
  );
}
