// Action is an inner <Text onPress> so it reads as one sentence with only the action underlined.
import { Text } from "@/components/ui/text";

interface AuthSwitchLinkProps {
  prompt: string;
  actionLabel: string;
  onPress: () => void;
}

export function AuthSwitchLink({
  prompt,
  actionLabel,
  onPress,
}: AuthSwitchLinkProps) {
  return (
    <Text font="main-ui-body" color="text-04" className="text-center">
      {prompt}{" "}
      <Text
        font="main-ui-action"
        color="text-05"
        className="underline"
        onPress={onPress}
        accessibilityRole="link"
      >
        {actionLabel}
      </Text>
    </Text>
  );
}
