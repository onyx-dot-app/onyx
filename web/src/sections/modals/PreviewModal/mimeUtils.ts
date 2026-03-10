"use client";

const MIME_LANGUAGE_PREFIXES: Array<[prefix: string, language: string]> = [
  ["application/json", "json"],
  ["application/xml", "xml"],
  ["text/xml", "xml"],
  ["application/x-yaml", "yaml"],
  ["application/yaml", "yaml"],
  ["text/yaml", "yaml"],
  ["text/x-yaml", "yaml"],
];

export function getMimeLanguage(mimeType: string): string | null {
  return (
    MIME_LANGUAGE_PREFIXES.find(([prefix]) =>
      mimeType.startsWith(prefix)
    )?.[1] ?? null
  );
}
