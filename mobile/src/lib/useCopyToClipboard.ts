import { useCallback, useState } from "react";
import * as Clipboard from "expo-clipboard";

// Copy-to-clipboard with a transient "copied" flag that resets after 2s.
const COPIED_RESET_MS = 2000;

export interface UseCopyToClipboardResult {
  copied: boolean;
  copy: (text: string) => Promise<void>;
}

export function useCopyToClipboard(): UseCopyToClipboardResult {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async (text: string) => {
    await Clipboard.setStringAsync(text);
    setCopied(true);
    setTimeout(() => setCopied(false), COPIED_RESET_MS);
  }, []);

  return { copied, copy };
}
