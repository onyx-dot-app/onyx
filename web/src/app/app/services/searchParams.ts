import { ReadonlyURLSearchParams } from "next/navigation";

// search params
export const SEARCH_PARAM_NAMES = {
  CHAT_ID: "chatId",
  SEARCH_ID: "searchId",
  PERSONA_ID: "agentId",
  PROJECT_ID: "projectId",
  ALL_MY_DOCUMENTS: "allMyDocuments",
  // overrides
  TEMPERATURE: "temperature",
  MODEL_VERSION: "model-version",
  SYSTEM_PROMPT: "system-prompt",
  STRUCTURED_MODEL: "structured-model",
  // user message
  USER_PROMPT: "user-prompt",
  SUBMIT_ON_LOAD: "submit-on-load",
  // chat title
  TITLE: "title",
  FILES: "files",
  // for seeding chats
  SEEDED: "seeded",
  SEND_ON_LOAD: "send-on-load",

  // when sending a message for the first time, we don't want to reload the page
  // and cause a re-render
  SKIP_RELOAD: "skip-reload",
} as const;

export type SearchParamName =
  (typeof SEARCH_PARAM_NAMES)[keyof typeof SEARCH_PARAM_NAMES];

// Strict parsing on purpose: `searchParams.get()` returns strings, so a
// truthiness check would treat "false" as enabled.
function isFlagParamTrue(
  searchParams: ReadonlyURLSearchParams | null,
  paramName: SearchParamName
) {
  const rawValue = searchParams?.get(paramName);
  return rawValue === "true" || rawValue === "1";
}

export function shouldSubmitOnLoad(
  searchParams: ReadonlyURLSearchParams | null
) {
  return isFlagParamTrue(searchParams, SEARCH_PARAM_NAMES.SUBMIT_ON_LOAD);
}

export function shouldSendOnLoad(searchParams: ReadonlyURLSearchParams | null) {
  return isFlagParamTrue(searchParams, SEARCH_PARAM_NAMES.SEND_ON_LOAD);
}

/**
 * Parses the `agentId` search param. Returns null when absent or not a valid
 * integer, so callers can fall back to the default agent.
 */
export function getAgentIdFromSearchParam(
  searchParams: ReadonlyURLSearchParams | null
): number | null {
  const rawValue = searchParams?.get(SEARCH_PARAM_NAMES.PERSONA_ID);
  // Full-value check: parseInt alone would accept prefixes like "12abc".
  if (!rawValue || !/^\d+$/.test(rawValue)) {
    return null;
  }
  const parsed = Number(rawValue);
  return Number.isSafeInteger(parsed) ? parsed : null;
}
