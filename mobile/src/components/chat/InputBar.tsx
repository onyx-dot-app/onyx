import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ChatState } from "@/chat/interfaces";
import { Button } from "@/components/ui/button";
import { TextInput } from "@/components/ui/text-input";
import SvgArrowUp from "@/icons/arrow-up";
import SvgStop from "@/icons/stop";

interface InputBarProps {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  onStop: () => void;
  chatState: ChatState;
}

// Owns its bottom safe-area inset; ChatScreen's KeyboardStickyView lifts it over the keyboard.
export function InputBar({
  value,
  onChangeText,
  onSend,
  onStop,
  chatState,
}: InputBarProps) {
  const insets = useSafeAreaInsets();
  const isBusy = chatState === "loading" || chatState === "streaming";
  const canSend = value.trim().length > 0 && !isBusy;

  return (
    <View
      className="bg-background-neutral-00 px-16 pt-8"
      style={{ paddingBottom: insets.bottom + 8 }}
    >
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder="Message Onyx…"
        returnKeyType="send"
        onSubmitEditing={() => {
          if (canSend) onSend();
        }}
        // keep the keyboard up after send
        submitBehavior="submit"
        rightSlot={
          isBusy ? (
            <Button
              prominence="tertiary"
              icon={SvgStop}
              accessibilityLabel="Stop"
              onPress={onStop}
              className="rounded-12 border border-border-02"
            />
          ) : (
            <Button
              prominence="primary"
              icon={SvgArrowUp}
              accessibilityLabel="Send"
              onPress={onSend}
              disabled={!canSend}
            />
          )
        }
      />
    </View>
  );
}
