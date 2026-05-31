import { useState } from "react";
import { TextInput, View } from "react-native";

import { Button } from "@/components/opal";
import { ArrowUpIcon, PaperclipIcon, StopIcon } from "@/components/ui/icons";
import { useToken } from "@/theme/ThemeProvider";
import { typography } from "@/theme/generated/typography";
import { useSendMessage } from "@/chat/useSendMessage";
import { ModelSelectorTrigger } from "./ModelSelectorTrigger";

// Chat composer — ports web `AppInputBar.tsx` (container + text area + bottom
// toolbar). Phase 05 scope: static, web-faithful shell wired to send/stop. The
// model selector (phase 07) mounts in the right cluster, left of Send; the attach
// [+] icon is rendered but inert (file upload is a later phase).
//
// Tokens/sizes copied from web:
//   container  bg-background-neutral-00, rounded-16, shadow-01 (no border)
//   text area  px-3 py-2, main-ui-body, text-05, placeholder text-03, grow 44→200
//   toolbar    h-11, p-1, justify-between; left = attach, right = send/stop
//   send/stop  default-primary Button (theme-primary-05), arrow-up ↔ stop square

// Text area grows between these (web `useContentEditable` defaults).
const MIN_INPUT_HEIGHT = 24;
const MAX_INPUT_HEIGHT = 184; // 200px row − 16px (py-2) vertical padding

interface ChatInputBarProps {
  /** Session to send into. Null on a brand-new chat (send wiring lands later). */
  sessionId?: string | null;
}

export function ChatInputBar({ sessionId }: ChatInputBarProps) {
  const [message, setMessage] = useState("");

  const { send, stop, isStreaming } = useSendMessage(sessionId ?? "draft");

  const placeholderColor = useToken("text-03");
  const typedColor = useToken("text-05");
  const sendIconColor = useToken("text-inverted-05");
  const attachIconColor = useToken("text-03");
  // web shadow-01 is colored by --shadow-02, which is a faint WHITE glow in dark
  // mode (#ffffff1a) and a soft black shadow in light mode — that glow is what
  // separates the black bar from the black chat surface. The token already bakes
  // in the alpha, so shadowOpacity stays at 1.
  const shadowColor = useToken("shadow-02");

  const trimmed = message.trim();
  const sendDisabled = !isStreaming && trimmed.length === 0;

  function handleSendPress() {
    if (isStreaming) {
      stop();
      return;
    }
    if (!trimmed) return;
    void send(trimmed);
    setMessage("");
  }

  return (
    <View
      className="w-full rounded-[16px] bg-background-neutral-00"
      style={{
        // web shadow-01: 0 2 12 + 0 0 4 of --shadow-02 (no border)
        shadowColor,
        shadowOpacity: 1,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 2 },
        elevation: 4,
      }}
    >
      {/* Text area (web `:827` — px-3 py-2, grows with content) */}
      <View className="px-3 py-2">
        <TextInput
          value={message}
          onChangeText={setMessage}
          placeholder="How can I help you today?"
          placeholderTextColor={placeholderColor}
          multiline
          style={[
            typography["main-ui-body"],
            {
              color: typedColor,
              minHeight: MIN_INPUT_HEIGHT,
              maxHeight: MAX_INPUT_HEIGHT,
              padding: 0,
              textAlignVertical: "top",
            },
          ]}
        />
      </View>

      {/* Bottom toolbar (web `:540` — h-11, p-1, space-between) */}
      <View className="h-11 flex-row items-center justify-between px-1">
        {/* Left cluster: attach (inert in v1) */}
        <View className="flex-row items-center gap-1">
          <Button
            variant="default"
            prominence="tertiary"
            size="sm"
            className="w-8 px-0"
            accessibilityLabel="Attach files"
            onPress={() => {
              // TODO(phase): file upload pipeline (picker + upload + chips)
            }}
          >
            <PaperclipIcon size={16} color={attachIconColor} />
          </Button>
        </View>

        {/* Right cluster: model selector trigger + send/stop */}
        <View className="flex-row items-center gap-1">
          <ModelSelectorTrigger sessionId={sessionId ?? "draft"} />
          <Button
            variant="default"
            prominence="primary"
            size="md"
            className="w-9 px-0"
            disabled={sendDisabled}
            accessibilityLabel={isStreaming ? "Stop generating" : "Send message"}
            onPress={handleSendPress}
          >
            {isStreaming ? (
              <StopIcon size={16} color={sendIconColor} />
            ) : (
              <ArrowUpIcon size={16} color={sendIconColor} />
            )}
          </Button>
        </View>
      </View>
    </View>
  );
}
