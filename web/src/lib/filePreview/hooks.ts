import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { buildImgUrl } from "@/app/app/components/files/images/utils";
import {
  loadChatFilePreview,
  type ChatFilePreviewData,
} from "@/lib/filePreview/loadChatFilePreview";

export interface ChatFilePreviewState {
  data: ChatFilePreviewData | undefined;
  error: Error | undefined;
  // True until the first load ends, and again while a retry runs
  isLoading: boolean;
  // The raw file, which downloads also when the preview fails
  url: string;
  retry: () => void;
}

/**
 * Loads a chat file for its preview. The caller scopes the SWR cache to the
 * preview (`FilePreviewScope`), so its bytes go when the preview closes, and
 * a download still running stops. A chat file never changes, so the data is
 * not revalidated; a failed load loads again on `retry`.
 */
export function useChatFilePreview(
  fileId: string,
  displayName: string
): ChatFilePreviewState {
  const download = useRef<AbortController | null>(null);
  const pendingAbort = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    clearTimeout(pendingAbort.current);
    // Strict Mode mounts again at once, before the timer runs
    return () => {
      pendingAbort.current = setTimeout(() => download.current?.abort());
    };
  }, []);
  const { data, error, isLoading, mutate } = useSWR<ChatFilePreviewData, Error>(
    SWR_KEYS.chatFilePreview(fileId),
    () => {
      download.current = new AbortController();
      return loadChatFilePreview(fileId, displayName, download.current.signal);
    },
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      shouldRetryOnError: false,
    }
  );
  return useMemo(
    () => ({
      data,
      error,
      isLoading,
      url: buildImgUrl(fileId),
      retry: () => void mutate(),
    }),
    [data, error, isLoading, fileId, mutate]
  );
}

// A paged preview narrower than this starts without its thumbnails, so a
// phone's page keeps its width
const THUMBNAILS_MIN_PREVIEW_WIDTH = 480;

/**
 * The width of a paged preview, which holds its thumbnail column and its
 * page, and whether the column shows: the user's toggle, else whether the
 * preview is at least THUMBNAILS_MIN_PREVIEW_WIDTH wide. Until the user
 * toggles, it follows the width, as on a rotation. Put `observePreview` on
 * the element that holds the column and the page. It measures that element
 * when it mounts, before the first paint, so a narrow preview never shows the
 * column. A width of 0 means not measured: a preview that mounts in a hidden
 * tab has no width until it shows, and a hidden tab keeps its last width.
 */
export function useThumbnailColumn() {
  const [choice, setChoice] = useState<boolean | null>(null);
  const [previewWidth, setPreviewWidth] = useState(0);
  const observePreview = useCallback((preview: HTMLDivElement | null) => {
    if (!preview) return;
    // Untransformed, as the observer's contentRect (the row has no padding)
    const mounted = preview.clientWidth;
    if (mounted > 0) setPreviewWidth(mounted);
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0)
        setPreviewWidth(entry.contentRect.width);
    });
    // oxlint-disable-next-line react-doctor/effect-needs-cleanup -- React calls this ref's returned disposer on detachment.
    observer.observe(preview);
    return () => observer.disconnect();
  }, []);
  const show =
    choice ??
    (previewWidth === 0 || previewWidth >= THUMBNAILS_MIN_PREVIEW_WIDTH);
  return {
    observePreview,
    previewWidth,
    show,
    toggle: () => setChoice(!show),
  };
}
