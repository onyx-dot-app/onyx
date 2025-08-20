import React, { useEffect, useMemo } from "react";
import { FiImage, FiDownload, FiEye } from "react-icons/fi";
import {
  PacketType,
  ImageGenerationToolPacket,
  ImageGenerationToolStart,
  ImageGenerationToolDelta,
  SectionEnd,
  Packet,
} from "../../../services/streamingModels";
import { MessageRenderer, RenderType } from "../interfaces";
import { buildImgUrl } from "../../../components/files/images/utils";

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

  const imageUrls = images
    .filter((image) => image.id)
    .map((image) => buildImgUrl(image.id!));

  return {
    prompt,
    images,
    imageUrls,
    isGenerating,
    isComplete,
    error: false, // For now, we don't have error state in the packets
  };
}

export const ImageToolRenderer: MessageRenderer<
  ImageGenerationToolPacket,
  {}
> = ({ packets, onComplete, renderType }) => {
  const { prompt, images, imageUrls, isGenerating, isComplete, error } =
    constructCurrentImageState(packets);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete]);

  const status = useMemo(() => {
    if (isComplete) {
      return `Generated ${imageUrls.length} image${
        imageUrls.length > 1 ? "s" : ""
      }`;
    }
    if (isGenerating) {
      return "Generating image...";
    }
    return null;
  }, [isComplete, isGenerating, imageUrls.length]);

  // Render based on renderType
  if (renderType === RenderType.FULL) {
    // Full rendering with title header and content below
    // Loading state - when generating
    if (isGenerating) {
      return {
        icon: FiImage,
        status: "Generating images...",
        content: (
          <div className="flex flex-col">
            {/* Title header with icon */}
            <div className="flex items-center gap-3 mb-3">
              <div className="flex-shrink-0 w-4 h-4 flex items-center justify-center">
                <FiImage className="w-4 h-4 text-gray-600 dark:text-gray-400" />
              </div>
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                Generating images{prompt && ` "${prompt}"`}
              </span>
            </div>

            {/* Content below - loading indicator */}
            <div className="flex items-center gap-2 ml-7">
              <div className="flex gap-0.5">
                <div className="w-1 h-1 bg-gray-500 rounded-full animate-bounce"></div>
                <div
                  className="w-1 h-1 bg-gray-500 rounded-full animate-bounce"
                  style={{ animationDelay: "0.1s" }}
                ></div>
                <div
                  className="w-1 h-1 bg-gray-500 rounded-full animate-bounce"
                  style={{ animationDelay: "0.2s" }}
                ></div>
              </div>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Please wait...
              </span>
            </div>
          </div>
        ),
      };
    }

    // Complete state - show images
    if (isComplete) {
      return {
        icon: FiImage,
        status: `Generated ${images.length} image${
          images.length !== 1 ? "s" : ""
        }`,
        content: (
          <div className="flex flex-col">
            {/* Title header with icon */}
            <div className="flex items-center gap-3 mb-3">
              <div className="flex-shrink-0 w-4 h-4 flex items-center justify-center">
                <FiImage className="w-4 h-4 text-gray-600 dark:text-gray-400" />
              </div>
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                {prompt && `"${prompt}"`} • {images.length} image
                {images.length !== 1 ? "s" : ""} generated
              </span>
            </div>

            {/* Content below - images */}
            {images.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 ml-7">
                {images.map(
                  (image: { [key: string]: string }, index: number) => (
                    <div
                      key={image.id || index}
                      className="bg-gray-50 dark:bg-gray-800 p-4 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-all group"
                    >
                      {/* Image */}
                      {image.id && (
                        <div className="relative mb-3">
                          <img
                            src={buildImgUrl(image.id)}
                            alt={image.prompt || "Generated image"}
                            className="w-full h-48 object-cover rounded-lg"
                            loading="lazy"
                          />
                          <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                            <button
                              onClick={() =>
                                window.open(buildImgUrl(image.id!), "_blank")
                              }
                              className="bg-black bg-opacity-50 text-white p-1.5 rounded hover:bg-opacity-70 transition-colors"
                              title="View full size"
                            >
                              <FiEye className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => {
                                const link = document.createElement("a");
                                link.href = buildImgUrl(image.id!);
                                link.download = `generated-image-${
                                  index + 1
                                }.png`;
                                link.click();
                              }}
                              className="bg-black bg-opacity-50 text-white p-1.5 rounded hover:bg-opacity-70 transition-colors"
                              title="Download"
                            >
                              <FiDownload className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Prompt */}
                      {image.prompt && (
                        <div className="text-sm text-gray-600 dark:text-gray-400 line-clamp-2 leading-relaxed">
                          <span className="font-medium">Prompt:</span>{" "}
                          {image.prompt}
                        </div>
                      )}
                    </div>
                  )
                )}
              </div>
            ) : (
              <div className="py-4 text-center text-gray-500 dark:text-gray-400 ml-7">
                <FiImage className="w-6 h-6 mx-auto mb-2 opacity-50" />
                <p className="text-sm">No images generated</p>
              </div>
            )}
          </div>
        ),
      };
    }

    // Fallback (shouldn't happen in normal flow)
    return {
      icon: FiImage,
      status: null,
      content: <div></div>,
    };
  }

  // Highlight/Short rendering
  if (isGenerating) {
    return {
      icon: FiImage,
      status: "Generating image...",
      content: (
        <div className="text-sm text-muted-foreground">Generating image...</div>
      ),
    };
  }

  if (error) {
    return {
      icon: FiImage,
      status: "Image generation failed",
      content: (
        <div className="text-sm text-red-600 dark:text-red-400">
          Image generation failed
        </div>
      ),
    };
  }

  if (isComplete && imageUrls.length > 0) {
    return {
      icon: FiImage,
      status: `Generated ${imageUrls.length} image${
        imageUrls.length > 1 ? "s" : ""
      }`,
      content: (
        <div className="text-sm text-muted-foreground">
          Generated {imageUrls.length} image
          {imageUrls.length > 1 ? "s" : ""}
        </div>
      ),
    };
  }

  return {
    icon: FiImage,
    status: "Image generation",
    content: (
      <div className="text-sm text-muted-foreground">Image generation</div>
    ),
  };
};
