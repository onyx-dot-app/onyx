import { useState } from "react";
import { Pressable, TextInput, View } from "react-native";

import { Button } from "@/components/opal";
import { SvgArrowUp } from "@/components/icons/SvgArrowUp";
import { SvgPaperclip } from "@/components/icons/SvgPaperclip";
import { SvgStop } from "@/components/icons/SvgStop";
import { useToken } from "@/theme/ThemeProvider";
import { typography } from "@/theme/generated/typography";
import { useSendMessage, useComposerAttachments } from "@/chat";
import { useActiveModel } from "@/chat/useActiveModel";
import { modelSupportsImageInput } from "@/lib/languageModels";
import {
  DRAFT_SESSION_ID,
  useCurrentPersonaId,
} from "@/state/chatSessionStore";
import { usePersonas, resolveAgent } from "@/query/personas";
import { useForcedTools } from "@/state/useForcedTools";
import { ActionsPopover } from "@/components/chat/actions/ActionsPopover";
import { ForcedToolChip } from "@/components/chat/actions/ForcedToolChip";
import { ModelSelectorTrigger } from "./ModelSelectorTrigger";
import { AttachMenu } from "./AttachMenu";
import { AttachmentTray } from "./AttachmentTray";

// Native mirror of web AppInputBar.

// Text area grows between these (web useContentEditable defaults).
const MIN_INPUT_HEIGHT = 24;
const MAX_INPUT_HEIGHT = 184; // 200px row − 16px (py-2) vertical padding

interface ChatInputBarProps {
  // Null on a brand-new chat (uses the "draft" key).
  sessionId?: string | null;
  disabled?: boolean;
}

export function ChatInputBar({ sessionId, disabled = false }: ChatInputBarProps) {
  const sid = sessionId ?? DRAFT_SESSION_ID;
  const [message, setMessage] = useState("");

  const { send, stop, isStreaming } = useSendMessage(sid);

  const personaId = useCurrentPersonaId();
  const { data: personas } = usePersonas();
  // Fall back to the default assistant on a fresh/draft chat so the actions
  // trigger appears immediately — mirrors the send path.
  const agent = resolveAgent(personas, personaId);
  const forcedToolIds = useForcedTools((s) => s.forcedToolIds);

  const {
    tiles,
    attachedFileIds,
    isUploading,
    attachments,
    addImages,
    addDocuments,
    addRecentFile,
    removeByFileId,
    remove,
    clear,
    toFileDescriptors,
  } = useComposerAttachments();

  // Vision gate. Default to allowed until providers load so we never falsely
  // block before we know the model.
  const { providers, activeModel } = useActiveModel(sid);
  const imagesAllowed = activeModel
    ? modelSupportsImageInput(providers, activeModel.modelName, activeModel.name)
    : true;

  const placeholderColor = useToken("text-03");
  const typedColor = useToken("text-05");
  // shadow-02 is a faint white glow in dark mode that separates the bar from the
  // chat surface; the token bakes in the alpha, so shadowOpacity stays at 1.
  const shadowColor = useToken("shadow-02");

  const trimmed = message.trim();
  const hasSendableAttachment = attachments.some(
    (a) => a.fileId && a.status !== "failed",
  );
  // Disabled unless streaming (→ stop), while loading/uploading, or with nothing to send.
  const sendDisabled =
    !isStreaming &&
    (disabled ||
      isUploading ||
      (trimmed.length === 0 && !hasSendableAttachment));

  function handleSendPress() {
    if (isStreaming) {
      stop();
      return;
    }
    if (disabled || isUploading) return;
    const descriptors = toFileDescriptors();
    if (!trimmed && descriptors.length === 0) return;
    // Clear only once committed (onAccepted), so a failed lazy session-creation
    // never discards the user's text + attachments.
    void send(trimmed, descriptors, () => {
      setMessage("");
      clear();
    });
  }

  return (
    <View
      className="w-full rounded-[16px] bg-background-neutral-00"
      style={{
        shadowColor,
        shadowOpacity: 1,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 2 },
        elevation: 4,
      }}
    >
      {tiles.length > 0 ? (
        <View className="px-1 pt-1">
          <AttachmentTray models={tiles} onRemove={remove} />
        </View>
      ) : null}

      <View className="px-3 py-2">
        <TextInput
          value={message}
          onChangeText={setMessage}
          placeholder="How can I help you today?"
          placeholderTextColor={placeholderColor}
          editable={!disabled}
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

      <View className="h-11 flex-row items-center justify-between px-1">
        <View className="flex-row items-center gap-1">
          <AttachMenu
            imagesAllowed={imagesAllowed}
            attachedFileIds={attachedFileIds}
            onPickImages={addImages}
            onPickDocuments={addDocuments}
            onPickRecent={addRecentFile}
            onUnpickRecent={(file) => removeByFileId(file.file_id)}
            trigger={
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Attach files"
                hitSlop={8}
                className="h-8 w-8 items-center justify-center rounded-[8px] active:bg-background-tint-02"
              >
                <SvgPaperclip size={16} color="text-03" />
              </Pressable>
            }
          />
          {agent && agent.tools.length > 0 ? (
            <ActionsPopover agent={agent} personaId={agent.id} />
          ) : null}
          {forcedToolIds.map((id) => {
            const tool = agent?.tools.find((t) => t.id === id);
            return tool ? (
              <ForcedToolChip
                key={id}
                tool={tool}
                onClear={() => useForcedTools.getState().toggleForcedTool(id)}
              />
            ) : null;
          })}
        </View>

        <View className="flex-row items-center gap-1">
          <ModelSelectorTrigger sessionId={sid} />
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
              <SvgStop size={16} color="text-inverted-05" />
            ) : (
              <SvgArrowUp size={16} color="text-inverted-05" />
            )}
          </Button>
        </View>
      </View>
    </View>
  );
}
