// ImageToolRenderer.tsx — the image-generation tool block.
//
// Ported from web:
//   web/src/app/app/message/messageComponents/renderers/ImageToolRenderer.tsx
//
// Scans IMAGE_GENERATION_TOOL_START + IMAGE_GENERATION_TOOL_DELTA packets
// (images: { file_id, url, ... }[]). While generating (start, no section end)
// it shows a "Generating image…" label + a pulsing placeholder. Once complete
// (start + section end / error) it shows a column of generated images.
//
// AMENDMENTS vs web:
//   • icon is the string name "image" (mobile contract), not the SvgImage
//     component — the timeline shell maps the name to the glyph.
//   • Web's `InMessageImage` (next/image + cookie auth, full-image modal,
//     download-on-hover) collapses to an `expo-image` <Image> with bearer auth
//     headers from `useAuthImageHeaders` and the `chatFileUrl` route helper —
//     mirroring `MessageRow` / `AttachmentTile`. No modal / download / hover.
//   • Web's animated GeneratingImageDisplay (96×96 SVG progress ring) collapses
//     to a full-width, aspect-1 tinted box with a BlinkingBar — RN-idiomatic.

import { useMemo } from "react";
import { View } from "react-native";
import { Image } from "expo-image";

import {
  PacketType,
  type ImageGenerationToolDelta,
  type ImageGenerationToolPacket,
  type ImageGenerationToolStart,
} from "@/lib/types";
import { Text } from "@/components/opal";
import { BlinkingBar } from "@/components/message/BlinkingBar";
import type { MessageRendererProps } from "@/components/message/interfaces";
import { useAuthImageHeaders } from "@/components/chat/useAuthImageHeaders";
import { chatFileUrl } from "@/lib/api";
import { appConfig } from "@/lib/config";
import { useToken } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import { useFireOnComplete } from "@/state/timeline/hooks/useFireOnComplete";

interface GeneratedImage {
  file_id: string;
  url: string;
  revised_prompt: string;
  shape?: string;
}

interface ImageState {
  images: GeneratedImage[];
  isGenerating: boolean;
  isComplete: boolean;
  error: boolean;
}

// Reduce the packet list to the current image-generation state. Mirrors the web
// `constructCurrentImageState`: find the START packet, flatten DELTA images, and
// treat SECTION_END / ERROR as the terminal "end" marker.
function constructCurrentImageState(
  packets: ImageGenerationToolPacket[]
): ImageState {
  const imageStart = packets.find(
    (packet) => packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_START
  )?.obj as ImageGenerationToolStart | undefined;

  const imageDeltas = packets
    .filter((packet) => packet.obj.type === PacketType.IMAGE_GENERATION_TOOL_DELTA)
    .map((packet) => packet.obj as ImageGenerationToolDelta);

  const imageEnd = packets.find(
    (packet) =>
      packet.obj.type === PacketType.SECTION_END ||
      packet.obj.type === PacketType.ERROR
  )?.obj;

  const images = imageDeltas.flatMap((delta) => delta?.images ?? []);
  const isGenerating = Boolean(imageStart) && !imageEnd;
  const isComplete = Boolean(imageStart) && Boolean(imageEnd);

  return {
    images,
    isGenerating,
    isComplete,
    // The packets don't carry an explicit error state yet (web parity).
    error: false,
  };
}

// ---------------------------------------------------------------------------
// GeneratedImageTile — one generated image (expo-image + bearer auth headers).
// ---------------------------------------------------------------------------

interface GeneratedImageTileProps {
  fileId: string;
}

function GeneratedImageTile({ fileId }: GeneratedImageTileProps) {
  const placeholderBg = useToken("background-tint-02");
  const borderColor = useToken("border-01");
  // Wait for the bearer header before loading the authed /chat/file URL so we
  // don't fire a guaranteed-401 request on first paint (web rides cookies).
  const headers = useAuthImageHeaders();

  const source = useMemo(
    () =>
      headers
        ? { uri: chatFileUrl(appConfig.apiBaseUrl, fileId), headers }
        : undefined,
    [headers, fileId]
  );

  return (
    <View
      style={{
        width: "100%",
        aspectRatio: 1,
        borderRadius: radii["12"],
        borderWidth: 1,
        borderColor,
        backgroundColor: placeholderBg,
        overflow: "hidden",
      }}
    >
      {source ? (
        <Image
          source={source}
          style={{ width: "100%", height: "100%" }}
          contentFit="contain"
          cachePolicy="memory-disk"
        />
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// GeneratingImagePlaceholder — full-width, aspect-1 tinted box + BlinkingBar.
// RN-idiomatic stand-in for web's animated SVG progress ring.
// ---------------------------------------------------------------------------

function GeneratingImagePlaceholder() {
  const placeholderBg = useToken("background-tint-02");
  const borderColor = useToken("border-01");
  return (
    <View
      style={{
        width: "100%",
        aspectRatio: 1,
        borderRadius: radii["12"],
        borderWidth: 1,
        borderColor,
        backgroundColor: placeholderBg,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <BlinkingBar />
    </View>
  );
}

export function ImageToolRenderer({
  packets,
  onComplete,
  renderType: _renderType,
  children,
}: MessageRendererProps<ImageGenerationToolPacket>) {
  const { images, isGenerating, isComplete, error } = useMemo(
    () => constructCurrentImageState(packets),
    [packets]
  );

  // Fire onComplete once, when the tool reaches its terminal state (web parity).
  useFireOnComplete(isComplete, onComplete);

  // Generating: label (text-03) + pulsing placeholder. Web shows the same
  // "Generating images..." status across all render types.
  if (isGenerating) {
    return children([
      {
        icon: "image",
        status: "Generating image…",
        supportsCollapsible: false,
        content: (
          <View style={{ gap: 8, marginVertical: 4 }}>
            <Text font="main-ui-muted" color="text-03">
              Generating image…
            </Text>
            <GeneratingImagePlaceholder />
          </View>
        ),
      },
    ]);
  }

  if (error) {
    return children([
      {
        icon: "image",
        status: "Image generation failed",
        supportsCollapsible: false,
        surfaceBackground: "error",
        content: (
          <Text font="main-ui-muted" color="status-error-05">
            Image generation failed
          </Text>
        ),
      },
    ]);
  }

  // Complete: a column of the generated images (full-width, aspect-1, rounded).
  if (isComplete) {
    const count = images.length;
    return children([
      {
        icon: "image",
        status: `Generated ${count} image${count !== 1 ? "s" : ""}`,
        supportsCollapsible: false,
        content:
          count > 0 ? (
            <View style={{ gap: 16, marginVertical: 4 }}>
              {images.map((image, index) => (
                <GeneratedImageTile
                  key={image.file_id || String(index)}
                  fileId={image.file_id}
                />
              ))}
            </View>
          ) : (
            <Text font="main-ui-muted" color="text-04">
              No images generated
            </Text>
          ),
      },
    ]);
  }

  // Fallback (shouldn't happen in normal flow — neither start nor end seen).
  return children([
    {
      icon: "image",
      status: "Image generation",
      supportsCollapsible: false,
      content: (
        <Text font="main-ui-muted" color="text-03">
          Image generation
        </Text>
      ),
    },
  ]);
}

export default ImageToolRenderer;
