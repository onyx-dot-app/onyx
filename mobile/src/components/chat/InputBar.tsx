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

// Auto-grow bounds (web parity: input `min-h-[44px]`, scrolls once it fills). We let the native
// multiline TextInput size itself between these — never a JS-computed fixed height — so the caret
// can't escape the frame (the old fixed-height approach let a fast double-Enter paint the caret
// behind the toolbar).
const INPUT_MIN_HEIGHT = 44;
const INPUT_MAX_HEIGHT = 160;

// web `shadow-box-01` (tokens/shadow.json): `0px 2px 12px 0px var(--shadow-02)` + a tight
// `0px 0px 4px 1px` layer; `--shadow-02` = 10% black in both light & dark. RN renders one layer,
// so we mirror the primary blur; Android uses `elevation`.
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

// Web-parity composer (mirrors web's Base/AppInputBar): a shadowed, borderless rounded card holding
// an attachment chip strip, an auto-growing multi-line input, and a bottom toolbar with the attach
// control (left) and stop/send (right). The left group is a slot — actions popover, model selector,
// deep research, mic, etc. drop in beside the paperclip as those features land. ChatScreen's
// KeyboardStickyView lifts the whole thing over the keyboard.
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

  // Recent library files (fetched only while the picker is open), minus what's already attached.
  const { data: recentFiles = [], isLoading: isLoadingRecent } =
    useRecentFiles(pickerOpen);
  const linkableRecent = useMemo(() => {
    const attachedIds = new Set(attachments.files.map((file) => file.id));
    return recentFiles.filter((file) => !attachedIds.has(file.id));
  }, [attachments.files, recentFiles]);

  const hasFiles = attachments.files.length > 0;
  const hasFailed = attachments.files.some(isFailedFile);
  const blockingMessage = hasFailed
    ? "Remove the failed attachment to send."
    : "Attaching files…";

  return (
    <View
      className="bg-background-neutral-00 px-12 pt-8"
      style={{ paddingBottom: insets.bottom }}
    >
      {/* Borderless-with-shadow on web; RN also keeps a hairline border — in dark mode the card and
          the page behind it are both near-black, where the black shadow is invisible, so the border
          guarantees the card reads in both themes. The shadow supplies the light-mode depth. */}
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
            textPresets["main-content-body"] as TextStyle,
            {
              minHeight: INPUT_MIN_HEIGHT,
              maxHeight: INPUT_MAX_HEIGHT,
              textAlignVertical: "top",
            },
          ]}
        />

        {attachments.hasBlockingFiles ? (
          <Text
            font="secondary-body"
            color={hasFailed ? "status-error-05" : "text-02"}
            className="px-12 pb-4"
          >
            {blockingMessage}
          </Text>
        ) : null}

        <View className="min-h-40 flex-row items-center justify-between p-4">
          {/* Left group — attach today; actions popover / model / deep research mount here later. */}
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
