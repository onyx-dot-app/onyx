import { useTranslations } from "next-intl";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { Text } from "@opal/components";
import { CardGrid, Section } from "@opal/layouts";
import {
  GeneratedImage,
  IMAGE_GENERATION_TOOL_TYPE,
  ImageGenerationToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import { MessageRenderer } from "@/app/app/message/messageComponents/types";
import { isGroupEndPacket } from "@/lib/timeline/chat/packetHelpers";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";

interface GeneratedImageGridProps {
  images: GeneratedImage[];
}

/** The generated images of a response, shown at the top of its answer. */
export function GeneratedImageGrid({ images }: GeneratedImageGridProps) {
  return (
    <CardGrid gap={4}>
      {images.map((image) => (
        <InMessageImage
          key={image.file_id}
          fileId={image.file_id}
          shape={image.shape}
        />
      ))}
    </CardGrid>
  );
}

/**
 * ImageToolRenderer - one image generation call in the timeline.
 *
 * The images themselves show in the answer (GeneratedImageGrid), so the step
 * shows the model's prompt as it streams in, and the provider's revised
 * prompts once done.
 */
export const ImageToolRenderer: MessageRenderer<
  ImageGenerationToolPacket,
  {}
> = ({ packets, stopPacketSeen, children }) => {
  const t = useTranslations("chat.messages");
  const images = Array.from(
    new Map(
      packets.flatMap((packet) =>
        packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA
          ? packet.obj.images.map((image) => [image.file_id, image] as const)
          : []
      )
    ).values()
  );
  const hasResult = packets.some(
    (packet) => packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA
  );
  const isComplete = packets.some(isGroupEndPacket);
  const isRunning = !isComplete && !stopPacketSeen;

  // A failed or stopped step keeps the running title. A final result can be
  // empty. A call with no result packet was stopped, by Stop or by an
  // interrupted code mode program.
  const status = t("imageTool.generatingStatus.text");
  const doneStatus =
    images.length > 0
      ? t("imageTool.generatedStatus.text", { count: images.length })
      : hasResult
        ? t("imageTool.emptyState.text")
        : t("imageTool.stoppedStatus.text");

  // The model's prompt, as it streams in before the call starts.
  const prompt = packets
    .map((packet) =>
      packet.obj.type === PacketType.TOOL_CALL_ARGUMENT_DELTA &&
      packet.obj.tool_type === IMAGE_GENERATION_TOOL_TYPE
        ? String(packet.obj.argument_deltas.prompt ?? "")
        : ""
    )
    .join("");
  const revisedPrompts = Array.from(
    new Set(images.map((image) => image.revised_prompt).filter(Boolean))
  );
  // The revised prompts replace the model's once the images arrive; a
  // provider that does not revise keeps the model's.
  // The streaming prompt keeps one key, so it updates in place.
  const prompts =
    isRunning || revisedPrompts.length === 0
      ? prompt
        ? [{ key: "prompt", text: prompt }]
        : []
      : revisedPrompts.map((text) => ({ key: text, text }));

  const content =
    prompts.length > 0 ? (
      <Section gap={1} alignItems="start" justifyContent="start" height="auto">
        {prompts.map(({ key, text }) => (
          <Text key={key} as="p" font="secondary-body" color="text-04">
            {text}
          </Text>
        ))}
      </Section>
    ) : null;

  return children([
    {
      icon: STEP_ICONS.image,
      status,
      doneStatus,
      supportsCollapsible: false,
      content,
    },
  ]);
};
