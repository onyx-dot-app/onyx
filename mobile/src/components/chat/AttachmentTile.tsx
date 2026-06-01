import { memo } from "react";
import { Pressable, View } from "react-native";
import { Image } from "expo-image";

import { Spinner, Text } from "@/components/opal";
import { SvgFileText } from "@/components/icons/SvgFileText";
import { SvgX } from "@/components/icons/SvgX";
import { useToken } from "@/theme/ThemeProvider";
import { fileExtensionLabel } from "@/lib/fileTypes";

// ---------------------------------------------------------------------------
// AttachmentTile — native mirror of web `FileCard`.
//
//   • Image  → thumbnail with a translucent spinner scrim while the file uploads
//              (web shows a spinner only; mobile has the local URI, so the preview
//              shows underneath the scrim).
//   • File   → bordered chip: icon (or spinner) + name + type / status label.
//   • Remove → button shown once the upload POST resolves (status ≠ "uploading").
//
// Shared by the composer (removable) and sent message bubbles (read-only).
// ---------------------------------------------------------------------------

export type AttachmentTileStatus =
  | "uploading"
  | "processing"
  | "uploaded"
  | "failed";

/** Normalized, render-ready attachment model (composer + bubbles map into this). */
export interface AttachmentTileModel {
  /** Stable key for list rendering + removal. */
  id: string;
  name: string;
  isImage: boolean;
  status: AttachmentTileStatus;
  /** expo-image source for image tiles — a local URI or an authed remote URL. */
  imageSource?: { uri: string; headers?: Record<string, string> };
}

interface AttachmentTileProps {
  model: AttachmentTileModel;
  /** Render images at 44×44 instead of 80×80 (web "compact" — 2+ images). */
  compact?: boolean;
  /** When provided, renders the remove affordance (hidden while uploading). */
  onRemove?: (id: string) => void;
}

function statusLabel(status: AttachmentTileStatus, fallback: string): string {
  switch (status) {
    case "uploading":
      return "Uploading…";
    case "processing":
      return "Processing…";
    case "failed":
      return "Failed";
    default:
      return fallback;
  }
}

function AttachmentTileComponent({
  model,
  compact = false,
  onRemove,
}: AttachmentTileProps) {
  // Remove-button and upload-scrim colours.
  const removeBg = useToken("background-neutral-inverted-01");
  const removeBorder = useToken("border-02");
  const shadow = useToken("shadow-02");
  const scrim = useToken("mask-03");

  // web: remove allowed once the upload POST resolves (status ≠ UPLOADING).
  const showRemove = onRemove != null && model.status !== "uploading";
  const inFlight = model.status === "uploading" || model.status === "processing";

  const removeButton = showRemove ? (
    <View
      // Sibling of the (overflow-clipped) tile body so it isn't clipped; offset
      // -8/-8 over the top-left corner, matching web's `-left-2 -top-2`.
      className="absolute -left-2 -top-2 z-10"
      style={{
        shadowColor: shadow,
        shadowOpacity: 1,
        shadowRadius: 2,
        shadowOffset: { width: 0, height: 1 },
        elevation: 2,
      }}
    >
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Remove ${model.name}`}
        hitSlop={8}
        onPress={() => onRemove?.(model.id)}
        className="h-4 w-4 items-center justify-center rounded-[4px] border active:opacity-90"
        style={{ backgroundColor: removeBg, borderColor: removeBorder }}
      >
        <SvgX size={12} color="text-inverted-03" />
      </Pressable>
    </View>
  ) : null;

  if (model.isImage) {
    const dimension = compact ? 44 : 80;
    const spinnerSize = compact ? 20 : 32;
    return (
      <View className="relative">
        <View
          className="overflow-hidden rounded-[8px] border border-border-01 bg-background-neutral-02"
          style={{ width: dimension, height: dimension }}
        >
          {model.imageSource ? (
            <Image
              source={model.imageSource}
              style={{ width: "100%", height: "100%" }}
              contentFit="cover"
              cachePolicy="memory-disk"
            />
          ) : (
            <View className="h-full w-full items-center justify-center">
              <SvgFileText size={spinnerSize} color="text-03" />
            </View>
          )}
          {inFlight ? (
            <View
              className="absolute inset-0 items-center justify-center"
              style={{ backgroundColor: scrim }}
            >
              <Spinner size={spinnerSize} color="text-inverted-05" />
            </View>
          ) : null}
        </View>
        {removeButton}
      </View>
    );
  }

  // Non-image: bordered file chip (web AttachmentItemLayout inside Interactive.Container).
  return (
    <View className="relative">
      <View className="max-w-[192px] flex-row items-center gap-2 rounded-[8px] border border-border-01 bg-background-neutral-00 px-2 py-1.5">
        <View className="h-9 w-9 items-center justify-center">
          {inFlight ? (
            <Spinner size={20} color="text-03" />
          ) : (
            <SvgFileText size={20} color="text-03" />
          )}
        </View>
        <View className="min-w-0 flex-1 pr-1">
          <Text font="main-ui-body" color="text-05" numberOfLines={1}>
            {model.name}
          </Text>
          <Text font="secondary-body" color="text-03" numberOfLines={1}>
            {statusLabel(
              model.status,
              fileExtensionLabel(model.name, { plaintextForTxt: false }),
            )}
          </Text>
        </View>
      </View>
      {removeButton}
    </View>
  );
}

const AttachmentTile = memo(AttachmentTileComponent);
AttachmentTile.displayName = "AttachmentTile";

export { AttachmentTile };
