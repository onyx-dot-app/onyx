import { Alert } from "react-native";
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";

import { isImageFile } from "@/lib/fileTypes";
import type { UploadableFile } from "@/lib/api";

// Shared file-picking logic for the composer's AttachMenu and the project file
// picker. Wraps expo's image/document pickers, maps their assets into
// `UploadableFile`s, and surfaces the same error Alerts. Each caller passes its
// own handler for the resulting files (attach optimistically vs. upload to a
// project) and decides whether to enforce the vision gate.

const VISION_MSG =
  "The current model does not support image input. Pick a model with Vision support to attach images.";

// Best-effort filename from a local URI when the picker reports none.
function nameFromUri(uri: string, fallback: string): string {
  const seg = (uri.split("/").pop() ?? "").split("?")[0] ?? "";
  return seg.includes(".") ? decodeURIComponent(seg) : fallback;
}

interface UseFilePickerOptions {
  /**
   * Whether the active model accepts images (vision gate). When false, Photos
   * picks are blocked and any images chosen via the document picker are filtered
   * out with an explanatory Alert. Defaults to `true` (no gate).
   */
  imagesAllowed?: boolean;
}

export interface UseFilePickerResult {
  /** Open the photo library and forward the picked images to `onFiles`. */
  pickImages: (onFiles: (files: UploadableFile[]) => void) => Promise<void>;
  /** Open the document picker and forward the picked documents to `onFiles`. */
  pickDocuments: (onFiles: (files: UploadableFile[]) => void) => Promise<void>;
}

export function useFilePicker({
  imagesAllowed = true,
}: UseFilePickerOptions = {}): UseFilePickerResult {
  async function pickImages(onFiles: (files: UploadableFile[]) => void) {
    if (!imagesAllowed) {
      Alert.alert("Images not supported", VISION_MSG);
      return;
    }
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        allowsMultipleSelection: true,
        quality: 1,
      });
      if (result.canceled) return;
      const files: UploadableFile[] = result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.fileName ?? nameFromUri(asset.uri, "image.jpg"),
        mimeType: asset.mimeType,
      }));
      if (files.length > 0) onFiles(files);
    } catch {
      Alert.alert("Couldn't open photos", "Please try again.");
    }
  }

  async function pickDocuments(onFiles: (files: UploadableFile[]) => void) {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        multiple: true,
        copyToCacheDirectory: true,
      });
      if (result.canceled) return;
      let files: UploadableFile[] = result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.name,
        mimeType: asset.mimeType,
      }));
      // The document picker can return images too — enforce the same vision gate
      // here so it can't bypass the Photos guard (web gates at the upload layer).
      if (!imagesAllowed) {
        const hadImages = files.some((file) => isImageFile(file.name));
        files = files.filter((file) => !isImageFile(file.name));
        if (hadImages) Alert.alert("Images not supported", VISION_MSG);
      }
      if (files.length > 0) onFiles(files);
    } catch {
      Alert.alert("Couldn't open files", "Please try again.");
    }
  }

  return { pickImages, pickDocuments };
}
