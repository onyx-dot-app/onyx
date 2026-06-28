import { View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { TextInput } from "@/components/ui/text-input";
import SvgArrowRightCircle from "@/icons/arrow-right-circle";

interface InputBarProps {
  // Disabled shell until PR 3 wires up text state + streaming send.
  disabled?: boolean;
}

// Mobile analog of web's `AppInputBar`.
export function InputBar({ disabled = true }: InputBarProps) {
  return (
    <View className="px-4 pb-2 pt-2">
      <TextInput
        variant={disabled ? "disabled" : "idle"}
        placeholder="Message Onyx…"
        rightSlot={
          <Icon as={SvgArrowRightCircle} size={24} className="text-text-02" />
        }
      />
    </View>
  );
}
