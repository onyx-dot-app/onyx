/**
 * "unknown" - webapp-info hasn't loaded yet for this session.
 * "none" - webapp-info loaded, no webapp has ever been scaffolded.
 * "starting" - webapp scaffolded (has_webapp) but not yet serving.
 * "ready" - server has been observed ready at least once (latched).
 */
export type WebappState = "unknown" | "none" | "starting" | "ready";

export const NO_WEBAPP_LABEL = "No web app in this session yet";
