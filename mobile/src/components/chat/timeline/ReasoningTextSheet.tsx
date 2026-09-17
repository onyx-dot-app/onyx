// Web's ExpandableTextDisplay modal, on the shared bottom-sheet shell. Download is dropped (no
// mobile analog for a .txt download); Copy is labelled rather than icon-only because mobile has no
// tooltip to explain a bare glyph.
import * as Clipboard from "expo-clipboard";
import { ScrollView, useWindowDimensions, View } from "react-native";

import { countLines, formatContentSize } from "@/chat/timeline/textStats";
import { StreamingMarkdown } from "@/components/chat/StreamingMarkdown";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/sheet";
import { Text } from "@/components/ui/text";
import { toast } from "@/hooks/useToast";

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
  const { height: screenHeight } = useWindowDimensions();
  const lineCount = countLines(content);

  async function handleCopy() {
    await Clipboard.setStringAsync(content);
    toast.success("Copied");
  }

  return (
    <Sheet
      visible={visible}
      onClose={onClose}
      title="Full text"
      subtitle={formatContentSize(content)}
    >
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
    </Sheet>
  );
}

export default ReasoningTextSheet;
