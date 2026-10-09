// Kept out of the sheet so they stay reanimated-free and unit-testable — the sheet pulls
// StreamingMarkdown → worklets, which crashes jest.
const BYTES_PER_KB = 1024;

// Hermes has no TextEncoder, so count UTF-8 bytes directly to match web's `new Blob([text]).size`.
export function utf8ByteLength(text: string): number {
  let bytes = 0;
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code < 0x80) {
      bytes += 1;
    } else if (code < 0x800) {
      bytes += 2;
    } else if (code >= 0xd800 && code <= 0xdbff) {
      // Surrogate pair: 4 bytes total, and the low half is consumed here.
      bytes += 4;
      index += 1;
    } else {
      bytes += 3;
    }
  }
  return bytes;
}

export function formatContentSize(text: string): string {
  const bytes = utf8ByteLength(text);
  if (bytes < BYTES_PER_KB) {
    return `${bytes} Bytes`;
  }
  return `${(bytes / BYTES_PER_KB).toFixed(2)} KB`;
}

export function countLines(text: string): number {
  return text.split("\n").length;
}
