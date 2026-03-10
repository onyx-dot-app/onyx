const MIME_LANGUAGE_PREFIXES: Array<[prefix: string, language: string]> = [
  ["application/json", "json"],
  ["application/xml", "xml"],
  ["text/xml", "xml"],
  ["application/x-yaml", "yaml"],
  ["application/yaml", "yaml"],
  ["text/yaml", "yaml"],
  ["text/x-yaml", "yaml"],
];

const OCTET_STREAM_EXTENSION_TO_MIME: Record<string, string> = {
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".txt": "text/plain",
  ".log": "text/plain",
  ".conf": "text/plain",
  ".sql": "text/plain",
  ".csv": "text/csv",
  ".tsv": "text/tab-separated-values",
  ".json": "application/json",
  ".xml": "application/xml",
  ".yml": "application/x-yaml",
  ".yaml": "application/x-yaml",
};

export function getMimeLanguage(mimeType: string): string | null {
  return (
    MIME_LANGUAGE_PREFIXES.find(([prefix]) =>
      mimeType.startsWith(prefix)
    )?.[1] ?? null
  );
}

export function resolveMimeType(mimeType: string, fileName: string): string {
  if (mimeType !== "application/octet-stream") {
    return mimeType;
  }

  const lowerFileName = fileName.toLowerCase();

  for (const [extension, resolvedMime] of Object.entries(
    OCTET_STREAM_EXTENSION_TO_MIME
  )) {
    if (lowerFileName.endsWith(extension)) {
      return resolvedMime;
    }
  }

  return mimeType;
}
