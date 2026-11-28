// search params
export const SEARCH_PARAM_NAMES = {
  CHAT_ID: "chatId",
  SEARCH_ID: "searchId",
  // An artifact link opened from outside the chat: the chat opens the file's
  // version in its panel, then drops them
  ARTIFACT_ID: "artifactId",
  ARTIFACT_VERSION: "artifactVersion",
  AGENT_ID: "agentId",
  // The subagent of the open chat that the main view shows
  SUBAGENT_ID: "subagent",
  PROJECT_ID: "projectId",
  ALL_MY_DOCUMENTS: "allMyDocuments",
  // overrides
  TEMPERATURE: "temperature",
  MODEL_VERSION: "model-version",
  SYSTEM_PROMPT: "system-prompt",
  STRUCTURED_MODEL: "structured-model",
  // user message
  USER_PROMPT: "user-prompt",
  // Comma-separated names of the chat skills the user prompt mentions.
  SKILLS: "skills",
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

export function shouldSubmitOnLoad(searchParams: URLSearchParams | null) {
  const rawSubmitOnLoad = searchParams?.get(SEARCH_PARAM_NAMES.SUBMIT_ON_LOAD);
  if (rawSubmitOnLoad === "true" || rawSubmitOnLoad === "1") {
    return true;
  }
  return false;
}
