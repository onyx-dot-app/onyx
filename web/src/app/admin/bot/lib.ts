import {
  ChannelConfig,
  SlackBotResponseType,
  SlackBotTokens,
} from "@/lib/types";
import { Persona } from "../assistants/interfaces";

interface SlackBotConfigCreationRequest {
  document_sets: number[];
  persona_id: number | null;
  enable_auto_filters: boolean;
  channel_names: string[];
  answer_validity_check_enabled: boolean;
  questionmark_prefilter_enabled: boolean;
  respond_tag_only: boolean;
  respond_to_bots: boolean;
  respond_member_group_list: string[];
  follow_up_tags?: string[];
  usePersona: boolean;
  response_type: SlackBotResponseType;
  standard_answer_categories: number[];
}

const buildFiltersFromCreationRequest = (
  creationRequest: SlackBotConfigCreationRequest
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
  creationRequest: SlackBotConfigCreationRequest
) => {
  return JSON.stringify({
    channel_names: creationRequest.channel_names,
    respond_tag_only: creationRequest.respond_tag_only,
    respond_to_bots: creationRequest.respond_to_bots,
    enable_auto_filters: creationRequest.enable_auto_filters,
    respond_member_group_list: creationRequest.respond_member_group_list,
    answer_filters: buildFiltersFromCreationRequest(creationRequest),
    follow_up_tags: creationRequest.follow_up_tags?.filter((tag) => tag !== ""),
    ...(creationRequest.usePersona
      ? { persona_id: creationRequest.persona_id }
      : { document_sets: creationRequest.document_sets }),
    response_type: creationRequest.response_type,
    standard_answer_categories: creationRequest.standard_answer_categories,
  });
};

export const createSlackBotConfig = async (
  creationRequest: SlackBotConfigCreationRequest
) => {
  return fetch("/api/manage/admin/slack-bot/config", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const updateSlackBotConfig = async (
  id: number,
  creationRequest: SlackBotConfigCreationRequest
) => {
  return fetch(`/api/manage/admin/slack-bot/config/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromCreationRequest(creationRequest),
  });
};

export const deleteSlackBotConfig = async (id: number) => {
  return fetch(`/api/manage/admin/slack-bot/config/${id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

export const setSlackBotTokens = async (slackBotTokens: SlackBotTokens) => {
  return fetch(`/api/manage/admin/slack-bot/tokens`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(slackBotTokens),
  });
};

export function isPersonaASlackBotPersona(persona: Persona) {
  return persona.name.startsWith("__slack_bot_persona__");
}
