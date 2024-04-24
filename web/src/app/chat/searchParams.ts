import { ReadonlyURLSearchParams } from "next/navigation";

// search params
export const SEARCH_PARAM_NAMES = {
  CHAT_ID: "chatId",
  PERSONA_ID: "assistantId",
  // overrides
  TEMPERATURE: "temperature",
  MODEL_VERSION: "model-version",
  SYSTEM_PROMPT: "system-prompt",
  // user message
  USER_MESSAGE: "user-message",
  SUBMIT_ON_LOAD: "submit-on-load",
  // chat title
  TITLE: "title",
};

export function shouldSubmitOnLoad(searchParams: ReadonlyURLSearchParams) {
  const rawSubmitOnLoad = searchParams.get(SEARCH_PARAM_NAMES.SUBMIT_ON_LOAD);
  if (rawSubmitOnLoad === "true" || rawSubmitOnLoad === "1") {
    return true;
  }
  return false;
}
