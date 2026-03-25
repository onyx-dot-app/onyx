type ClipboardFileItem = {
  kind: string;
  getAsFile: () => File | null;
};

type ClipboardDataLike = {
  items?: ArrayLike<ClipboardFileItem> | null;
  getData: (format: string) => string;
};

function getClipboardText(
  clipboardData: ClipboardDataLike,
  format: "text/plain" | "text"
): string {
  try {
    return clipboardData.getData(format);
  } catch {
    return "";
  }
}

export function getPastedFilesIfNoText(
  clipboardData?: ClipboardDataLike | null
): File[] {
  if (!clipboardData) {
    return [];
  }

  const plainText = getClipboardText(clipboardData, "text/plain").trim();
  const fallbackText = getClipboardText(clipboardData, "text").trim();

  // Apps like PowerPoint on macOS can place both rendered image data and the
  // original text on the clipboard. Prefer letting the textarea consume text.
  if (plainText || fallbackText || !clipboardData.items) {
    return [];
  }

  const pastedFiles: File[] = [];
  for (let i = 0; i < clipboardData.items.length; i++) {
    const item = clipboardData.items[i];
    if (item?.kind !== "file") {
      continue;
    }

    const file = item.getAsFile();
    if (file) {
      pastedFiles.push(file);
    }
  }

  return pastedFiles;
}
