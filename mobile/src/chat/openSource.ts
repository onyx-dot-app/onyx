// Where a source opens. Inline marker taps use `openUrl` directly (the `[[n]](url)` marker already
// carries the doc URL); source-row taps use `openSource`, which also handles link-less file docs.

import * as WebBrowser from "expo-web-browser";

import { SearchDoc } from "@/chat/contracts/documents";
import { toast } from "@/hooks/useToast";

export type SourceTarget =
  | { kind: "browser"; url: string }
  | { kind: "file"; fileId: string }
  | { kind: "none" };

const HTTP_RE = /^https?:\/\//i;

export function isHttpUrl(url: string): boolean {
  return HTTP_RE.test(url);
}

export function documentTarget(doc: SearchDoc): SourceTarget {
  if (doc.link && isHttpUrl(doc.link))
    return { kind: "browser", url: doc.link };
  if (doc.file_id) return { kind: "file", fileId: doc.file_id };
  return { kind: "none" };
}

// In-app browser (SFSafariViewController / Chrome Custom Tabs) — keeps the user in the app.
export function openUrl(url: string): void {
  if (!isHttpUrl(url)) return;
  void WebBrowser.openBrowserAsync(url).catch(() => {
    toast.error("Couldn't open this link.");
  });
}

export function openSource(doc: SearchDoc): void {
  const target = documentTarget(doc);
  switch (target.kind) {
    case "browser":
      openUrl(target.url);
      break;
    case "file":
      // File/internal source with no public link; no mobile doc preview yet.
      toast.info("Preview isn't available on mobile yet.");
      break;
    case "none":
      break;
  }
}
