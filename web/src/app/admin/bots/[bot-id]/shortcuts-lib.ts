import { SlackBotResponseType } from "@/lib/types";
import { Persona } from "@/app/admin/assistants/interfaces";

interface SlackShortcutConfigCreationRequest {
  slack_bot_id: number;
  document_sets: number[];
  persona_id: number | null;
  enable_auto_filters: boolean;
  shortcut_name: string;
  default_message: string;
  answer_validity_check_enabled: boolean;
  is_ephemeral: boolean;
  show_continue_in_web_ui: boolean;
  respond_member_group_list: string[];
  follow_up_tags?: string[];
  usePersona: boolean;
  response_type: SlackBotResponseType;
  standard_answer_categories: number[];
  disabled: boolean;
}

const buildFiltersFromCreationRequest = (
  creationRequest: SlackShortcutConfigCreationRequest
): string[] => {
  const answerFilters = [] as string[];
  if (creationRequest.answer_validity_check_enabled) {
    answerFilters.push("well_answered_postfilter");
  }
  return answerFilters;
};

const buildRequestBodyFromCreationRequest = (
  creationRequest: SlackShortcutConfigCreationRequest
) => {
  return JSON.stringify({
    slack_bot_id: creationRequest.slack_bot_id,
    shortcut_name: creationRequest.shortcut_name,
    default_message: creationRequest.default_message,
    is_ephemeral: creationRequest.is_ephemeral,
    show_continue_in_web_ui: creationRequest.show_continue_in_web_ui,
    respond_member_group_list: creationRequest.respond_member_group_list,
    answer_filters: buildFiltersFromCreationRequest(creationRequest),
    follow_up_tags: creationRequest.follow_up_tags?.filter((tag) => tag !== ""),
    disabled: creationRequest.disabled,
    enable_auto_filters: creationRequest.enable_auto_filters,
    ...(creationRequest.usePersona
      ? { persona_id: creationRequest.persona_id }
      : { document_sets: creationRequest.document_sets }),
    response_type: creationRequest.response_type,
    standard_answer_categories: creationRequest.standard_answer_categories,
  });
};

export const createSlackShortcutConfig = async (
  creationRequest: SlackShortcutConfigCreationRequest
) => {
  return fetch("/api/manage/admin/slack-app/shortcut", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const updateSlackShortcutConfig = async (
  id: number,
  creationRequest: SlackShortcutConfigCreationRequest
) => {
  return fetch(`/api/manage/admin/slack-app/shortcut/${id}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const deleteSlackShortcutConfig = async (id: number) => {
  return fetch(`/api/manage/admin/slack-app/shortcut/${id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

export function isPersonaASlackBotPersona(persona: Persona) {
  return persona.name.startsWith("__slack_bot_persona__");
}