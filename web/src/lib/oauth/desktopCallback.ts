// "." is outside the base64url alphabet every state generator uses.
export const DESKTOP_STATE_SUFFIX = ".desktop";

/** Page served in place of a callback that must go back to the desktop app. */
export const DESKTOP_HANDOFF_PATH = "/oauth/desktop-handoff";

// Same allowlist as desktop/src-tauri/src/oauth_handoff.rs.
const CALLBACK_PATHS = new Set([
  "/mcp/oauth/callback",
  "/federated/oauth/callback",
  "/craft/v1/apps/oauth/callback",
  "/oauth-config/callback",
]);
const CALLBACK_PATTERNS = [
  /^\/admin\/connectors\/[A-Za-z0-9_-]+\/oauth\/callback$/,
  /^\/connector\/oauth\/callback\/[A-Za-z0-9_-]+$/,
];

/**
 * True for a callback that a desktop-started attempt reached in the browser.
 * It goes back to the app, so the browser needs no Onyx session for it.
 */
export function isDesktopOAuthCallback(
  pathname: string,
  state: string | null
): boolean {
  if (!state?.endsWith(DESKTOP_STATE_SUFFIX)) return false;
  return (
    CALLBACK_PATHS.has(pathname) ||
    CALLBACK_PATTERNS.some((pattern) => pattern.test(pathname))
  );
}
