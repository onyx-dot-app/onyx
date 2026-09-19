import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
// Type-only, so this pure module never pulls the upload transport (and its config/MMKV chain).
import type { NormalizedAsset } from "@/api/files/upload";

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "heic", "bmp"];

// Uppercase extension without the dot; "" when there's no usable extension.
export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return "";
  return name.slice(dot + 1).toUpperCase();
}

export function isImageName(name: string): boolean {
  return IMAGE_EXTENSIONS.includes(extensionOf(name).toLowerCase());
}

// Status casing isn't guaranteed by the payload.
export function isFailedFile(file: ProjectFile): boolean {
  return String(file.status).toUpperCase() === UserFileStatus.FAILED;
}

// Optimistic record shown immediately on pick, before the server responds. `id`/`file_id`
// are the temp id until the upload reconciles. Shared by the project + per-message flows.
export function buildOptimisticFile(
  asset: NormalizedAsset,
  tempId: string,
): ProjectFile {
  return {
    id: tempId,
    temp_id: tempId,
    name: asset.name,
    file_id: tempId,
    status: UserFileStatus.UPLOADING,
    chat_file_type: asset.mimeType?.startsWith("image/")
      ? ChatFileType.IMAGE
      : ChatFileType.DOCUMENT,
    token_count: null,
    created_at: new Date().toISOString(),
  };
}

// Finite fallback when the server setting is missing/0 (mirrors the backend default), so an
// oversize file fails the client precheck instead of only server-side.
export const DEFAULT_MAX_UPLOAD_MB = 100;

export function resolveMaxUploadMb(maxUploadMb: number | null): number {
  return maxUploadMb != null && maxUploadMb > 0
    ? maxUploadMb
    : DEFAULT_MAX_UPLOAD_MB;
}

// Client-side upload size guard (mirrors web). Shared by the project + per-message flows.
export function partitionBySize(
  assets: NormalizedAsset[],
  maxUploadMb: number | null,
): { valid: NormalizedAsset[]; rejections: string[] } {
  const limitMb = resolveMaxUploadMb(maxUploadMb);
  const maxBytes = limitMb * 1024 * 1024;
  const rejections: string[] = [];
  const valid = assets.filter((asset) => {
    if (asset.size != null && asset.size > maxBytes) {
      rejections.push(`${asset.name} exceeds the ${limitMb} MB limit`);
      return false;
    }
    return true;
  });
  return { valid, rejections };
}

// Human status line for a file card/chip. When idle, falls back to the extension
// ("File" avoids a lone filename) — matching web, which leaves it blank.
export function attachmentStatusLabel(
  file: ProjectFile,
  progress?: number,
): string {
  switch (String(file.status).toUpperCase()) {
    case UserFileStatus.UPLOADING:
      return progress != null
        ? `Uploading… ${Math.round(progress * 100)}%`
        : "Uploading…";
    case UserFileStatus.PROCESSING:
      return "Processing…";
    case UserFileStatus.INDEXING:
      return "Indexing…";
    case UserFileStatus.DELETING:
      return "Deleting…";
    case UserFileStatus.FAILED:
      return "Failed";
    default:
      return extensionOf(file.name) || "File";
  }
}
