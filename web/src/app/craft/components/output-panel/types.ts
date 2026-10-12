/**
 * "unknown" - webapp-info hasn't loaded yet for this session.
 * "none" - webapp-info loaded, no webapp has ever been scaffolded.
 * "starting" - webapp scaffolded (has_webapp) but not yet serving.
 * "ready" - server has been observed ready at least once (latched).
 */
export type WebappState = "unknown" | "none" | "starting" | "ready";

export function getWebappState(
  hasBeenReady: boolean,
  hasWebapp: boolean | null | undefined
): WebappState {
  if (hasBeenReady) return "ready";
  if (hasWebapp == null) return "unknown";
  return hasWebapp ? "starting" : "none";
}

export interface FilePreviewScrollPosition {
  initialScrollTop?: number;
  onScrollTopChange?: (scrollTop: number) => void;
  isActive?: boolean;
}
