// Web's ExpandableTextDisplay modal, on the same RN Modal + ScrollView bottom sheet as 9a's
// CitedSourcesSheet. Download is dropped (no mobile analog for a .txt download); Copy is labelled
// rather than icon-only because mobile has no tooltip to explain a bare glyph.
import * as Clipboard from "expo-clipboard";
import {
  Modal,
  Pressable,
  ScrollView,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { countLines, formatContentSize } from "@/chat/timeline/textStats";
import { StreamingMarkdown } from "@/components/chat/StreamingMarkdown";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import { toast } from "@/hooks/useToast";
import SvgX from "@/icons/x";

// Reasoning is long-form prose, so the body takes most of the screen — unlike 9a's Sources sheet,
// which wraps a short list. Capping the body (not the sheet) keeps a short reasoning sheet
// shrink-wrapped instead of stretching to a fixed height.
const BODY_MAX_SCREEN_FRACTION = 0.7;

export interface ReasoningTextSheetProps {
  visible: boolean;
  onClose: () => void;
  // Full reasoning, heading included — the window above shows it with the heading lifted out.
  content: string;
}

export function ReasoningTextSheet({
  visible,
  onClose,
  content,
}: ReasoningTextSheetProps) {
  const insets = useSafeAreaInsets();
  const { height: screenHeight } = useWindowDimensions();
  const lineCount = countLines(content);

  async function handleCopy() {
    await Clipboard.setStringAsync(content);
    toast.success("Copied");
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      {/* Semantic tokens are bare CSS vars with no alpha, so the dimming scrim needs a raw rgba. */}
      <Pressable
        className="flex-1 justify-end"
        style={{ backgroundColor: "rgba(0, 0, 0, 0.4)" }}
        onPress={onClose}
      >
        {/* Stop taps inside the sheet from dismissing it. */}
        <Pressable
          onPress={() => {}}
          className="rounded-t-20 border-t border-border-01 bg-background-tint-00 px-16 pt-16"
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          <View className="mb-8 flex-row items-start justify-between">
            <View className="flex-1">
              <Text font="main-content-emphasis" color="text-04">
                Full text
              </Text>
              <Text font="secondary-body" color="text-03">
                {formatContentSize(content)}
              </Text>
            </View>
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="sm"
              accessibilityLabel="Close"
              onPress={onClose}
            />
          </View>

          <ScrollView
            style={{
              maxHeight: Math.round(screenHeight * BODY_MAX_SCREEN_FRACTION),
            }}
            keyboardShouldPersistTaps="handled"
            contentContainerClassName="pb-8"
          >
            <StreamingMarkdown
              content={content}
              isStreaming={false}
              variant="muted"
            />
          </ScrollView>

          <View className="mt-8 flex-row items-center justify-between">
            <Text font="main-ui-muted" color="text-03">
              {lineCount} {lineCount === 1 ? "line" : "lines"}
            </Text>
            <Button prominence="tertiary" size="sm" onPress={handleCopy}>
              Copy
            </Button>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

export default ReasoningTextSheet;
