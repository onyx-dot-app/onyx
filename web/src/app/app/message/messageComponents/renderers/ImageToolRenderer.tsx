import { useTranslations } from "next-intl";
import { SvgImage } from "@opal/icons";
import { Text } from "@opal/components";
import { CardGrid, Section } from "@opal/layouts";
import {
  GeneratedImage,
  ImageGenerationToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/types";
import { isGroupEndPacket } from "@/lib/timeline/chat/packetHelpers";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import GeneratingImageDisplay from "@/app/app/components/tools/GeneratingImageDisplay";

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
 * shows a placeholder while it runs and the revised prompts when done.
 */
export const ImageToolRenderer: MessageRenderer<
  ImageGenerationToolPacket,
  {}
> = ({ packets, renderType, stopPacketSeen, children }) => {
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
  const failed = packets.some((p) => p.obj.type === PacketType.ERROR);
  const isRunning = !isComplete && !stopPacketSeen;

  // A final result can be empty. A call with no result packet was stopped, by
  // Stop or by an interrupted code mode program.
  const status = failed
    ? t("imageTool.failedStatus.text")
    : isRunning
      ? t("imageTool.generatingStatus.text")
      : images.length > 0
        ? t("imageTool.generatedStatus.text", { count: images.length })
        : hasResult
          ? t("imageTool.emptyState.text")
          : t("imageTool.stoppedStatus.text");

  const revisedPrompts = Array.from(
    new Set(images.map((image) => image.revised_prompt).filter(Boolean))
  );

  const content = isRunning ? (
    renderType === RenderType.FULL ? (
      <GeneratingImageDisplay isCompleted={false} />
    ) : (
      <></>
    )
  ) : (
    <Section gap={1} alignItems="start" justifyContent="start" height="auto">
      {revisedPrompts.map((prompt) => (
        <Text key={prompt} as="p" font="secondary-body" color="text-04">
          {prompt}
        </Text>
      ))}
    </Section>
  );

  return children([
    {
      icon: SvgImage,
      status,
      supportsCollapsible: false,
      content,
    },
  ]);
};
