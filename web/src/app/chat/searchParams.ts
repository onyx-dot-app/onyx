import { ReadonlyURLSearchParams } from "next/navigation";

// search params
export const SEARCH_PARAM_NAMES = {
  CHAT_ID: "chatId",
  SEARCH_ID: "searchId",
  PERSONA_ID: "assistantId",
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
  // for seeding chats
  SEEDED: "seeded",
  SEND_ON_LOAD: "send-on-load",
};

export function shouldSubmitOnLoad(searchParams: ReadonlyURLSearchParams) {
  const rawSubmitOnLoad = searchParams.get(SEARCH_PARAM_NAMES.SUBMIT_ON_LOAD);
  if (rawSubmitOnLoad === "true" || rawSubmitOnLoad === "1") {
    return true;
  }
  return false;
}
