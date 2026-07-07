import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";

import type { NormalizedAsset } from "@/api/files/upload";

function basename(uri: string): string {
  const cleaned = uri.split("?")[0];
  const last = cleaned.slice(cleaned.lastIndexOf("/") + 1);
  return last.length > 0 ? decodeURIComponent(last) : "file";
}

// No MIME allowlist (web has none); the backend rejects unsupported types.
export async function pickDocuments(): Promise<NormalizedAsset[]> {
  const result = await DocumentPicker.getDocumentAsync({
    multiple: true,
    copyToCacheDirectory: true,
  });
  if (result.canceled) return [];
  return result.assets.map((asset) => ({
    uri: asset.uri,
    name: asset.name,
    mimeType: asset.mimeType,
    size: asset.size,
  }));
}

// quality:1 avoids re-encoding, so the reported size stays stable for the file key.
export async function pickImages(): Promise<NormalizedAsset[]> {
  const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
  // Distinct from cancel (which returns []) so the caller can surface it.
  if (!permission.granted) {
    throw new Error(
      "Photo library access was denied. Enable it in Settings to add photos.",
    );
  }
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsMultipleSelection: true,
    quality: 1,
  });
  if (result.canceled) return [];
  return result.assets.map((asset) => ({
    uri: asset.uri,
    name: asset.fileName ?? basename(asset.uri),
    mimeType: asset.mimeType,
    size: asset.fileSize,
  }));
}
