import {
  startUpload,
  type NormalizedAsset,
  type StartedUpload,
} from "@/api/files/upload";

// The seam between the upload engine and the byte transfer: a foreground impl now, a background
// impl injected later via `configureUploadTransport` without the engine knowing which runs.
export type UploadHandle = StartedUpload;

export interface UploadTransport {
  kind: "foreground" | "background";
  upload(
    asset: NormalizedAsset,
    opts: { projectId: number | null; tempId: string },
    onProgress: (ratio: number) => void,
  ): UploadHandle;
}

const foregroundTransport: UploadTransport = {
  kind: "foreground",
  upload(asset, opts, onProgress) {
    return startUpload(asset, opts.projectId, opts.tempId, onProgress);
  },
};

let active: UploadTransport = foregroundTransport;

export function getUploadTransport(): UploadTransport {
  return active;
}

export function configureUploadTransport(transport: UploadTransport): void {
  active = transport;
}
