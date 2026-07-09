import { useMemo, useState } from "react";
import { Pressable, View, type TextStyle } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { textPresets } from "@onyx-ai/shared/native";

import { useRecentFiles } from "@/api/files/files";
import { FileCard } from "@/components/chat/FileCard";
import { FilePickerSheet } from "@/components/chat/FilePickerSheet";
import { Button } from "@/components/ui/button";
import { Text } from "@/components/ui/text";
import { FieldTextInput as ComposerInput } from "@/components/ui/text-input";
import { ChatState } from "@/chat/interfaces";
import { isFailedFile } from "@/lib/files";
import type { UseMessageAttachments } from "@/hooks/useMessageAttachments";
import SvgArrowUp from "@/icons/arrow-up";
import SvgPaperclip from "@/icons/paperclip";
import SvgStop from "@/icons/stop";

// Auto-grow bounds: one line → ~5 lines, then the field scrolls internally.
const INPUT_MIN_HEIGHT = 24;
const INPUT_MAX_HEIGHT = 120;

interface InputBarProps {
  value: string;
  onChangeText: (text: string) => void;
  onSend: () => void;
  onStop: () => void;
  chatState: ChatState;
  attachments: UseMessageAttachments;
}

// Web-parity composer (mirrors web's AppInputBar shape): a rounded container holding an
// attachment chip strip, an auto-growing multi-line input, and a control row with the
// attach button (left) and send/stop (right). ChatScreen's KeyboardStickyView lifts it
// over the keyboard.
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
  const [inputHeight, setInputHeight] = useState(INPUT_MIN_HEIGHT);

  const isBusy = chatState === "loading" || chatState === "streaming";
  const canSend =
    value.trim().length > 0 && !isBusy && !attachments.hasBlockingFiles;

  // Recent library files (fetched only while the picker is open), minus what's already attached.
  const { data: recentFiles = [], isLoading: isLoadingRecent } =
    useRecentFiles(pickerOpen);
  const linkableRecent = useMemo(() => {
    const attachedIds = new Set(attachments.files.map((file) => file.id));
    return recentFiles.filter((file) => !attachedIds.has(file.id));
  }, [attachments.files, recentFiles]);

  const hasFailed = attachments.files.some(isFailedFile);
  const blockingMessage = hasFailed
    ? "Remove the failed attachment to send."
    : "Attaching files…";

  const clampedHeight = Math.min(
    Math.max(inputHeight, INPUT_MIN_HEIGHT),
    INPUT_MAX_HEIGHT,
  );

  return (
    <View
      className="bg-background-neutral-00 px-16 pt-8"
      style={{ paddingBottom: insets.bottom + 8 }}
    >
      {attachments.errors.length > 0 ? (
        <Pressable
          onPress={attachments.dismissErrors}
          className="mb-8 gap-4 rounded-12 border border-border-01 px-12 py-8"
        >
          {attachments.errors.map((message, index) => (
            <Text
              key={`${index}:${message}`}
              font="secondary-body"
              color="status-error-05"
            >
              {message}
            </Text>
          ))}
          <Text font="secondary-body" color="text-03">
            Tap to dismiss
          </Text>
        </Pressable>
      ) : null}

      <View className="rounded-16 border border-border-01 bg-background-neutral-00 pt-8">
        {attachments.files.length > 0 ? (
          <View className="flex-row flex-wrap gap-8 px-12 pb-8">
            {attachments.files.map((file) => (
              <FileCard
                key={file.id}
                file={file}
                progress={attachments.progressById.get(file.id)}
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
          onContentSizeChange={(event) =>
            setInputHeight(event.nativeEvent.contentSize.height)
          }
          scrollEnabled={inputHeight > INPUT_MAX_HEIGHT}
          className="px-16 text-text-04"
          style={[
            textPresets["main-content-body"] as TextStyle,
            { height: clampedHeight, textAlignVertical: "top" },
          ]}
        />

        {attachments.hasBlockingFiles ? (
          <Text
            font="secondary-body"
            color={hasFailed ? "status-error-05" : "text-02"}
            className="px-16 pt-4"
          >
            {blockingMessage}
          </Text>
        ) : null}

        <View className="flex-row items-center justify-between px-8 pb-8 pt-4">
          <Button
            prominence="tertiary"
            size="sm"
            icon={SvgPaperclip}
            accessibilityLabel="Attach files"
            onPress={() => setPickerOpen(true)}
          />
          {isBusy ? (
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
          )}
        </View>
      </View>

      <FilePickerSheet
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onUploadDocuments={() => {
          setPickerOpen(false);
          void attachments.addDocuments();
        }}
        onUploadPhotos={() => {
          setPickerOpen(false);
          void attachments.addImages();
        }}
        recentFiles={linkableRecent}
        onPickRecent={(fileId) => {
          setPickerOpen(false);
          const file = linkableRecent.find((item) => item.id === fileId);
          if (file) attachments.addRecent(file);
        }}
        isLoadingRecent={isLoadingRecent}
      />
    </View>
  );
}
