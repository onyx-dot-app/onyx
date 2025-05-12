import { SlackShortcutConfig, StandardAnswerCategory } from "@/lib/types";
import { Persona } from "@/app/admin/assistants/interfaces";

export async function fetchSlackShortcutConfigs(
  slack_bot_id: number
): Promise<SlackShortcutConfig[]> {
  const response = await fetch(
    `/api/manage/admin/slack-app/bots/${slack_bot_id}/shortcuts`,
    {
      method: "GET",
    }
  );

  if (!response.ok) {
    throw new Error(
      `Failed to fetch Slack shortcut configs: ${await response.text()}`
    );
  }

  return await response.json();
}

export async function createSlackShortcutConfig(data: {
  slack_bot_id: number;
  shortcut_name: string;
  default_message: string;
  document_sets: number[];
  persona_id: number | null;
  response_type: "quotes" | "citations";
  answer_validity_check_enabled: boolean;
  is_ephemeral: boolean;
  respond_member_group_list: string[];
  still_need_help_enabled: boolean;
  follow_up_tags?: string[];
  standard_answer_categories: string[];
  usePersona: boolean;
  knowledge_source: string;
  enable_auto_filters: boolean;
  show_continue_in_web_ui: boolean;
  disabled?: boolean;
}) {
  // Convert answer filters to array of filter names
  const answer_filters = [];
  if (data.answer_validity_check_enabled) {
    answer_filters.push("well_answered_postfilter");
  }

  // Construct the payload
  const payload: Record<string, any> = {
    slack_bot_id: data.slack_bot_id,
    shortcut_config: {
      shortcut_name: data.shortcut_name,
      default_message: data.default_message,
      answer_filters,
      is_ephemeral: data.is_ephemeral,
      respond_member_group_list: data.respond_member_group_list,
      follow_up_tags: data.follow_up_tags,
      show_continue_in_web_ui: data.show_continue_in_web_ui,
    },
    standard_answer_categories: data.standard_answer_categories,
    response_type: data.response_type,
    enable_auto_filters: data.enable_auto_filters,
  };

  // Handle knowledge source
  if (data.knowledge_source === "all_public") {
    // Using all public knowledge, no specific document sets or persona
    payload.document_sets = [];
    payload.persona_id = null;
  } else if (data.knowledge_source === "document_sets") {
    // Using specific document sets
    payload.document_sets = data.document_sets;
    payload.persona_id = null;
  } else {
    // Using assistant (search or non-search)
    payload.document_sets = [];
    payload.persona_id = data.persona_id;
  }

  return await fetch(`/api/manage/admin/slack-app/shortcut`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function updateSlackShortcutConfig(
  shortcut_id: number,
  data: {
    slack_bot_id: number;
    shortcut_name: string;
    default_message: string;
    document_sets: number[];
    persona_id: number | null;
    response_type: "quotes" | "citations";
    answer_validity_check_enabled: boolean;
    is_ephemeral: boolean;
    respond_member_group_list: string[];
    still_need_help_enabled: boolean;
    follow_up_tags?: string[];
    standard_answer_categories: string[];
    usePersona: boolean;
    knowledge_source: string;
    enable_auto_filters: boolean;
    show_continue_in_web_ui: boolean;
    disabled?: boolean;
  }
) {
  // Convert answer filters to array of filter names
  const answer_filters = [];
  if (data.answer_validity_check_enabled) {
    answer_filters.push("well_answered_postfilter");
  }

  // Construct the payload
  const payload: Record<string, any> = {
    slack_bot_id: data.slack_bot_id,
    shortcut_config: {
      shortcut_name: data.shortcut_name,
      default_message: data.default_message,
      answer_filters,
      is_ephemeral: data.is_ephemeral,
      respond_member_group_list: data.respond_member_group_list,
      follow_up_tags: data.follow_up_tags,
      show_continue_in_web_ui: data.show_continue_in_web_ui,
      disabled: data.disabled,
    },
    standard_answer_categories: data.standard_answer_categories,
    response_type: data.response_type,
    enable_auto_filters: data.enable_auto_filters,
  };

  // Handle knowledge source
  if (data.knowledge_source === "all_public") {
    // Using all public knowledge, no specific document sets or persona
    payload.document_sets = [];
    payload.persona_id = null;
  } else if (data.knowledge_source === "document_sets") {
    // Using specific document sets
    payload.document_sets = data.document_sets;
    payload.persona_id = null;
  } else {
    // Using assistant (search or non-search)
    payload.document_sets = [];
    payload.persona_id = data.persona_id;
  }

  return await fetch(`/api/manage/admin/slack-app/shortcut/${shortcut_id}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export function isPersonaASlackBotPersona(persona: Persona): boolean {
  return persona.name.startsWith("SlackBot:");
}