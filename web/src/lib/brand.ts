// Single source of truth for the product brand. Replaces the hardcoded "Glomi AI"
// fallbacks scattered across the UI. Do NOT global-replace "Glomi AI" in the
// codebase - most occurrences are identifiers (@onyx-ai/*, SvgOnyxLogo, etc.).
export const APP_NAME = "Glomi AI";
