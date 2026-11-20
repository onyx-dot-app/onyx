import { useEffect, useMemo, useRef } from "react";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
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
      url: `/api/chat/file/${encodeURIComponent(fileId)}`,
      retry: () => void mutate(),
    }),
    [data, error, isLoading, fileId, mutate]
  );
}
