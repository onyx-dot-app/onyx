import { useMemo, useState } from "react";
import { View, type TextStyle } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { textPresets } from "@onyx-ai/shared/native";

import { useRecentFiles } from "@/hooks/useRecentFiles";
import { FileCard } from "@/components/chat/FileCard";
import { FilePickerSheet } from "@/components/chat/FilePickerSheet";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import { FieldTextInput as ComposerInput } from "@/components/ui/text-input";
import { ChatState } from "@/chat/interfaces";
import { isFailedFile } from "@/lib/files";
import type { UseComposerDraft } from "@/hooks/useComposerDraft";
import SvgArrowUp from "@/icons/arrow-up";
import SvgPaperclip from "@/icons/paperclip";
import SvgStop from "@/icons/stop";

// Fixed height via native min===max sizing, never a JS-computed height: a content-driven height
// let a fast double-Enter paint the caret behind the toolbar.
const INPUT_HEIGHT = 44;

// Mirrors web `shadow-box-01` (tokens/shadow.json); RN renders one layer so we keep the primary
// blur, Android uses `elevation`.
const SHADOW_BOX_01 = {
  shadowColor: "#000000",
  shadowOffset: { width: 0, height: 2 },
  shadowOpacity: 0.1,
  shadowRadius: 12,
  elevation: 4,
} as const;

interface InputBarProps {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  onStop: () => void;
  chatState: ChatState;
  attachments: UseComposerDraft;
}

export function InputBar({
  value,
  onChangeText,
  onSend,
  onStop,
  chatState,
  attachments,
}: InputBarProps) {
  const insets = useSafeAreaInsets();
  const [pickerOpen, setPickerOpen] = useState(false);

  const isBusy = chatState === "loading" || chatState === "streaming";
  const canSend =
    value.trim().length > 0 && !isBusy && !attachments.hasBlockingFiles;

  const { data: recentFiles = [], isLoading: isLoadingRecent } =
    useRecentFiles(pickerOpen);
  const linkableRecent = useMemo(() => {
    const attachedIds = new Set(attachments.files.map((file) => file.id));
    return recentFiles.filter((file) => !attachedIds.has(file.id));
  }, [attachments.files, recentFiles]);

  const hasFiles = attachments.files.length > 0;
  const hasFailed = attachments.files.some(isFailedFile);

  return (
    <View
      className="bg-background-neutral-00 px-12 pt-8"
      style={{ paddingBottom: insets.bottom }}
    >
      {/* Hairline border (web is borderless): in dark mode card and page are both near-black and the
          shadow is invisible, so the border guarantees the card reads. */}
      <View
        className="rounded-16 border border-border-01 bg-background-neutral-00"
        style={SHADOW_BOX_01}
      >
        {hasFiles ? (
          // gap-8 (wider than web's 4px): mobile file chips are larger touch targets.
          <View className="flex-row flex-wrap gap-8 px-12 pt-12">
            {attachments.files.map((file) => (
              <FileCard
                key={file.id}
                file={file}
                onRemove={attachments.removeFile}
              />
            ))}
          </View>
        ) : null}

        <ComposerInput
          value={value}
          onChangeText={onChangeText}
          placeholder="Message Onyx…"
          placeholderClassName="text-text-02"
          multiline
          className="px-12 pb-8 pt-12 text-text-04"
          style={[
            textPresets["main-ui-body"] as TextStyle,
            {
              minHeight: INPUT_HEIGHT,
              maxHeight: INPUT_HEIGHT,
              textAlignVertical: "top",
            },
          ]}
        />

        {/* Only the actionable failed hint; in-progress uploads show a spinner on the chip. */}
        {hasFailed ? (
          <Text
            font="secondary-body"
            color="status-error-05"
            className="px-12 pb-4"
          >
            Remove the failed attachment to send.
          </Text>
        ) : null}

        <View className="min-h-40 flex-row items-center justify-between p-4">
          <View className="flex-row items-center gap-8">
            <Button
              prominence="tertiary"
              icon={SvgPaperclip}
              accessibilityLabel="Attach files"
              onPress={() => setPickerOpen(true)}
            />
          </View>

          <View className="flex-row items-center gap-4">
            {isBusy ? (
              <Button
                prominence="tertiary"
                icon={SvgStop}
                accessibilityLabel="Stop"
                onPress={onStop}
                className="rounded-12 border-[1.5px] border-border-02"
              />
            ) : (
              <Button
                prominence="primary"
                icon={SvgArrowUp}
                accessibilityLabel="Send"
                onPress={onSend}
                disabled={!canSend}
              />
            )}
          </View>
        </View>
      </View>

      <FilePickerSheet
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        // Sheet closes itself (choose→onClose) and defers the action past dismiss — no setPickerOpen here.
        onUploadDocuments={() => void attachments.addDocuments()}
        onUploadPhotos={() => void attachments.addImages()}
        recentFiles={linkableRecent}
        onPickRecent={(fileId) => {
          const file = linkableRecent.find((item) => item.id === fileId);
          if (file) attachments.addRecent(file);
        }}
        isLoadingRecent={isLoadingRecent}
      />
    </View>
  );
}
