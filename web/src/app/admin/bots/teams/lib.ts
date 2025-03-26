import { TeamsBot, TeamsBotCreationRequest, TeamsChannelConfig } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

const TEAMS_BOTS_URL = "/api/manage/admin/teams-app/bots";

export async function createTeamsBot(request: TeamsBotCreationRequest): Promise<TeamsBot> {
  return errorHandlingFetcher(TEAMS_BOTS_URL, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function updateTeamsBot(
  id: string,
  request: Partial<TeamsBotCreationRequest>
): Promise<TeamsBot> {
  return errorHandlingFetcher(`${TEAMS_BOTS_URL}/${id}`, {
    method: "PATCH",
    body: JSON.stringify(request),
  });
}

export async function deleteTeamsBot(id: string): Promise<void> {
  return errorHandlingFetcher(`${TEAMS_BOTS_URL}/${id}`, {
    method: "DELETE",
  });
}

export async function updateTeamsBotField(
  teamsBot: TeamsBot,
  field: keyof TeamsBot,
  value: any
): Promise<TeamsBot> {
  return updateTeamsBot(teamsBot.id, { [field]: value });
}

export async function createTeamsChannelConfig(
  botId: string,
  request: Partial<TeamsChannelConfig>
): Promise<TeamsChannelConfig> {
  return errorHandlingFetcher(`${TEAMS_BOTS_URL}/${botId}/channels`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function updateTeamsChannelConfig(
  configId: string,
  request: Partial<TeamsChannelConfig>
): Promise<TeamsChannelConfig> {
  return errorHandlingFetcher(`${TEAMS_BOTS_URL}/channels/${configId}`, {
    method: "PATCH",
    body: JSON.stringify(request),
  });
}

export async function deleteTeamsChannelConfig(configId: string): Promise<void> {
  return errorHandlingFetcher(`${TEAMS_BOTS_URL}/channels/${configId}`, {
    method: "DELETE",
  });
}

export function isPersonaATeamsBotPersona(persona: any): boolean {
  return persona?.type === "teams_bot";
} 