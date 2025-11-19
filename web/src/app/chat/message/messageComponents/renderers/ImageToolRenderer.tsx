import React, { useEffect, useMemo } from "react";
import { FiImage } from "react-icons/fi";
import {
  PacketType,
  ImageGenerationToolPacket,
  ImageGenerationToolStart,
  ImageGenerationToolDelta,
  SectionEnd,
} from "../../../services/streamingModels";
import { MessageRenderer, RenderType } from "../interfaces";
import { InMessageImage } from "../../../components/files/images/InMessageImage";
import GeneratingImageDisplay from "../../../components/tools/GeneratingImageDisplay";

// Helper function to construct current image state
function constructCurrentImageState(packets: ImageGenerationToolPacket[]) {
  const imageStart = packets.find(
    (packet) => packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START
  )?.obj as ImageGenerationToolStart | null;
  const imageDeltas = packets
    .filter(
      (packet) => packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA
    )
    .map((packet) => packet.obj as ImageGenerationToolDelta);
  const imageEnd = packets.find(
    (packet) => packet.obj.type === PacketType.SECTION_END
  )?.obj as SectionEnd | null;

  const prompt = ""; // Image generation tools don't have a main description
  const images = imageDeltas.flatMap((delta) => delta?.images || []);
  const isGenerating = imageStart && !imageEnd;
  const isComplete = imageStart && imageEnd;

  return {
    prompt,
    images,
    isGenerating,
    isComplete,
    error: false, // For now, we don't have error state in the packets
  };
}

export const ImageToolRenderer: MessageRenderer<
  ImageGenerationToolPacket,
  {}
> = ({ packets, onComplete, renderType, children }) => {
  const { prompt, images, isGenerating, isComplete, error } =
    constructCurrentImageState(packets);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete]);

  const status = useMemo(() => {
    if (isComplete) {
      return `Generated ${images.length} image${images.length > 1 ? "s" : ""}`;
    }
    if (isGenerating) {
      return "Generating image...";
    }
    return null;
  }, [isComplete, isGenerating, images.length]);

  // Render based on renderType
  if (renderType === RenderType.FULL) {
    // Full rendering with title header and content below
    // Loading state - when generating
    if (isGenerating) {
      return children({
        icon: FiImage,
        status: "Generating images...",
        content: (
          <div className="flex flex-col">
            <div>
              <GeneratingImageDisplay isCompleted={false} />
            </div>
          </div>
        ),
      });
    }

    // Complete state - show images
    if (isComplete) {
      return children({
        icon: FiImage,
        status: `Generated ${images.length} image${
          images.length !== 1 ? "s" : ""
        }`,
        content: (
          <div className="flex flex-col my-1">
            {images.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {images.map((image, index: number) => (
                  <div
                    key={image.file_id || index}
                    className="transition-all group"
                  >
                    {image.file_id && (
                      <InMessageImage
                        fileId={image.file_id}
                        shape={image.shape}
                      />
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-4 text-center text-gray-500 dark:text-gray-400 ml-7">
                <FiImage className="w-6 h-6 mx-auto mb-2 opacity-50" />
                <p className="text-sm">No images generated</p>
              </div>
            )}
          </div>
        ),
      });
    }

    // Fallback (shouldn't happen in normal flow)
    return children({
      icon: FiImage,
      status: status,
      content: <div></div>,
    });
  }

  // Highlight/Short rendering
  if (isGenerating) {
    return children({
      icon: FiImage,
      status: "Generating image...",
      content: (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <div className="flex gap-0.5">
            <div className="w-1 h-1 bg-current rounded-full animate-pulse"></div>
            <div
              className="w-1 h-1 bg-current rounded-full animate-pulse"
              style={{ animationDelay: "0.1s" }}
            ></div>
            <div
              className="w-1 h-1 bg-current rounded-full animate-pulse"
              style={{ animationDelay: "0.2s" }}
            ></div>
          </div>
          <span>Generating image...</span>
        </div>
      ),
    });
  }

  if (error) {
    return children({
      icon: FiImage,
      status: "Image generation failed",
      content: (
        <div className="text-sm text-red-600 dark:text-red-400">
          Image generation failed
        </div>
      ),
    });
  }

  if (isComplete && images.length > 0) {
    return children({
      icon: FiImage,
      status: `Generated ${images.length} image${images.length > 1 ? "s" : ""}`,
      content: (
        <div className="text-sm text-muted-foreground">
          Generated {images.length} image
          {images.length > 1 ? "s" : ""}
        </div>
      ),
    });
  }

  return children({
    icon: FiImage,
    status: "Image generation",
    content: (
      <div className="text-sm text-muted-foreground">Image generation</div>
    ),
  });
};
