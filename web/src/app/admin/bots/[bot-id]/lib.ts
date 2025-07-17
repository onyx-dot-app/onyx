import { SlackBotResponseType } from "@/lib/types";
import { Persona } from "@/app/admin/assistants/interfaces";

interface SlackChannelConfigCreationRequest {
  slack_bot_id: number;
  document_sets: number[];
  persona_id: number | null;
  enable_auto_filters: boolean;
  channel_name: string;
  answer_validity_check_enabled: boolean;
  questionmark_prefilter_enabled: boolean;
  respond_tag_only: boolean;
  is_ephemeral: boolean;
  respond_to_bots: boolean;
  show_continue_in_web_ui: boolean;
  respond_member_group_list: string[];
  follow_up_tags?: string[];
  usePersona: boolean;
  response_type: SlackBotResponseType;
  standard_answer_categories: number[];
  disabled: boolean;
}

const buildFiltersFromCreationRequest = (
  creationRequest: SlackChannelConfigCreationRequest
): string[] => {
  const answerFilters = [] as string[];
  if (creationRequest.answer_validity_check_enabled) {
    answerFilters.push("well_answered_postfilter");
  }
  if (creationRequest.questionmark_prefilter_enabled) {
    answerFilters.push("questionmark_prefilter");
  }
  return answerFilters;
};

const buildRequestBodyFromCreationRequest = (
  creationRequest: SlackChannelConfigCreationRequest
) => {
  return JSON.stringify({
    slack_bot_id: creationRequest.slack_bot_id,
    channel_name: creationRequest.channel_name,
    respond_tag_only: creationRequest.respond_tag_only,
    respond_to_bots: creationRequest.respond_to_bots,
    is_ephemeral: creationRequest.is_ephemeral,
    show_continue_in_web_ui: creationRequest.show_continue_in_web_ui,
    enable_auto_filters: creationRequest.enable_auto_filters,
    respond_member_group_list: creationRequest.respond_member_group_list,
    answer_filters: buildFiltersFromCreationRequest(creationRequest),
    follow_up_tags: creationRequest.follow_up_tags?.filter((tag) => tag !== ""),
    ...(creationRequest.usePersona
      ? { persona_id: creationRequest.persona_id }
      : { document_sets: creationRequest.document_sets }),
    response_type: creationRequest.response_type,
    standard_answer_categories: creationRequest.standard_answer_categories,
    disabled: creationRequest.disabled,
  });
};

export const createSlackChannelConfig = async (
  creationRequest: SlackChannelConfigCreationRequest
) => {
  return fetch("/api/manage/admin/slack-app/channel", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const updateSlackChannelConfig = async (
  id: number,
  creationRequest: SlackChannelConfigCreationRequest
) => {
  return fetch(`/api/manage/admin/slack-app/channel/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const deleteSlackChannelConfig = async (id: number) => {
  return fetch(`/api/manage/admin/slack-app/channel/${id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

export function isPersonaASlackBotPersona(persona: Persona) {
  return persona.name.startsWith("__slack_bot_persona__");
}
