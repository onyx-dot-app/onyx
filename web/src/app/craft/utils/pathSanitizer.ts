/**
 * Path Sanitizer
 *
 * Pure string functions for stripping sandbox/session path prefixes.
 * All paths displayed in the UI must be relative to the session root.
 *
 * Two deployment shapes exist (both always include the sessions layer):
 *   Local:  /Users/.../sandboxes/{uuid}/sessions/{uuid}/outputs/web/page.tsx
 *   Kube:   /workspace/sessions/{uuid}/outputs/web/page.tsx
 */

/**
 * Strip sandbox/session path prefixes to produce a session-relative path.
 *
 * Returns the path relative to the session root (the directory that
 * contains outputs/, files/, etc.)
 */
export function stripSessionPrefix(fullPath: string): string {
  if (!fullPath) return "";

  // 1. .../sandboxes/{uuid}/sessions/{uuid}/REST  →  REST
  //    Matches local dev (always sandboxes + sessions)
  const sbSession = fullPath.match(
    /\/sandboxes\/[0-9a-f-]+\/sessions\/[0-9a-f-]+\/(.+)$/
  );
  if (sbSession?.[1]) return sbSession[1];

  // 2. .../sessions/{uuid}/REST  →  REST
  //    Matches kubernetes (e.g. /workspace/sessions/...)
  const session = fullPath.match(/\/sessions\/[0-9a-f-]+\/(.+)$/);
  if (session?.[1]) return session[1];

  // 3. Fallback: keep last 3 path segments for context
  //    /some/unknown/deep/path/to/file.tsx  →  path/to/file.tsx
  const segments = fullPath.split("/").filter(Boolean);
  if (segments.length > 3) return segments.slice(-3).join("/");

  // 4. Already relative or short — return as-is
  return fullPath.startsWith("/") ? fullPath.slice(1) : fullPath;
}

/**
 * Replace all absolute sandbox/session paths in freeform text with
 * session-relative paths.
 *
 * Handles paths embedded in commands, output listings, error messages, etc.
 * Matches both local and kubernetes path formats.
 */

// Pre-compiled regexes (module-level, not per-call)
// Order matters: most specific first to avoid partial matches
const SESSION_PATH_PATTERNS = [
  // Local: .../sandboxes/uuid/sessions/uuid/REST
  /(?:\/[\w._-]+)*\/sandboxes\/[0-9a-f-]+\/sessions\/[0-9a-f-]+\//g,
  // Kubernetes: .../sessions/uuid/REST  (no sandboxes prefix)
  /(?:\/[\w._-]+)*\/sessions\/[0-9a-f-]+\//g,
];

export function sanitizePathsInText(text: string): string {
  if (!text) return "";

  let result = text;
  for (const pattern of SESSION_PATH_PATTERNS) {
    // Reset lastIndex since we reuse the regex
    pattern.lastIndex = 0;
    result = result.replace(pattern, "");
  }
  return result;
}
