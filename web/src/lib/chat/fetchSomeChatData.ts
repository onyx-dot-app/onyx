import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { fetchSS } from "@/lib/utilsSS";
import {
  CCPairBasicInfo,
  DocumentSet,
  Tag,
  User,
  ValidSources,
} from "@/lib/types";
import { ChatSession } from "@/app/chat/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";
import { fetchLLMProvidersSS } from "@/lib/llm/fetchLLMs";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { Folder } from "@/app/chat/folders/interfaces";
import { personaComparator } from "@/app/admin/assistants/lib";
import { cookies } from "next/headers";
import {
  SIDEBAR_TOGGLED_COOKIE_NAME,
  DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME,
} from "@/components/resizable/constants";
import { hasCompletedWelcomeFlowSS } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { fetchAssistantsSS } from "../assistants/fetchAssistantsSS";
import { NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN } from "../constants";
import { checkLLMSupportsImageInput } from "../llm/utils";

interface FetchChatDataResult {
  user?: User | null;
  chatSessions?: ChatSession[];
  ccPairs?: CCPairBasicInfo[];
  availableSources?: ValidSources[];
  documentSets?: DocumentSet[];
  assistants?: Persona[];
  tags?: Tag[];
  llmProviders?: LLMProviderDescriptor[];
  folders?: Folder[];
  openedFolders?: Record<string, boolean>;
  defaultAssistantId?: number;
  toggleSidebar?: boolean;
  finalDocumentSidebarInitialWidth?: number;
  shouldShowWelcomeModal?: boolean;
  shouldDisplaySourcesIncompleteModal?: boolean;
}

type FetchOption =
  | "user"
  | "chatSessions"
  | "ccPairs"
  | "documentSets"
  | "assistants"
  | "tags"
  | "llmProviders"
  | "folders";

/* 
NOTE: currently unused, but leaving here for future use. 
*/
export async function fetchSomeChatData(
  searchParams: { [key: string]: string },
  fetchOptions: FetchOption[] = []
): Promise<FetchChatDataResult | { redirect: string }> {
  const requestCookies = await cookies();
  const tasks: Promise<any>[] = [];
  const taskMap: Record<FetchOption, () => Promise<any>> = {
    user: getCurrentUserSS,
    chatSessions: () => fetchSS("/chat/get-user-chat-sessions"),
    ccPairs: () => fetchSS("/manage/connector-status"),
    documentSets: () => fetchSS("/manage/document-set"),
    assistants: fetchAssistantsSS,
    tags: () => fetchSS("/query/valid-tags"),
    llmProviders: fetchLLMProvidersSS,
    folders: () => fetchSS("/folder"),
  };

  // Always fetch auth type metadata
  tasks.push(getAuthTypeMetadataSS());

  // Add tasks based on fetchOptions
  fetchOptions.forEach((option) => {
    if (taskMap[option]) {
      tasks.push(taskMap[option]());
    }
  });

  let results: any[] = await Promise.all(tasks);

  const authTypeMetadata = results.shift() as AuthTypeMetadata | null;
  const authDisabled = authTypeMetadata?.authType === "disabled";

  let user: User | null = null;

  if (fetchOptions.includes("user")) {
    user = results.shift();
    if (!authDisabled && !user) {
      return { redirect: "/auth/login" };
    }
    if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
      return { redirect: "/auth/waiting-on-verification" };
    }
  }

  const result: FetchChatDataResult = {};

  for (let i = 0; i < fetchOptions.length; i++) {
    const option = fetchOptions[i];
    const result = results[i];

    switch (option) {
      case "user":
        result.user = user;
        break;
      case "chatSessions":
        result.chatSessions = result?.ok
          ? ((await result.json()) as { sessions: ChatSession[] }).sessions
          : [];
        break;
      case "ccPairs":
        result.ccPairs = result?.ok
          ? ((await result.json()) as CCPairBasicInfo[])
          : [];
        break;
      case "documentSets":
        result.documentSets = result?.ok
          ? ((await result.json()) as DocumentSet[])
          : [];
        break;
      case "assistants":
        const [rawAssistantsList, assistantsFetchError] = result as [
          Persona[],
          string | null,
        ];
        result.assistants = rawAssistantsList
          .filter((assistant) => assistant.is_visible)
          .sort(personaComparator);
        break;
      case "tags":
        result.tags = result?.ok
          ? ((await result.json()) as { tags: Tag[] }).tags
          : [];
        break;
      case "llmProviders":
        result.llmProviders = result || [];
        break;
      case "folders":
        result.folders = result?.ok
          ? ((await result.json()) as { folders: Folder[] }).folders
          : [];
        break;
    }
  }

  if (result.ccPairs) {
    result.availableSources = Array.from(
      new Set(result.ccPairs.map((ccPair) => ccPair.source))
    );
  }

  if (result.chatSessions) {
    result.chatSessions.sort((a, b) => (a.id > b.id ? -1 : 1));
  }

  if (fetchOptions.includes("assistants") && result.assistants) {
    const hasAnyConnectors = result.ccPairs && result.ccPairs.length > 0;
    if (!hasAnyConnectors) {
      result.assistants = result.assistants.filter(
        (assistant) => assistant.num_chunks === 0
      );
    }

    const hasImageCompatibleModel = result.llmProviders?.some(
      (provider) =>
        provider.provider === "openai" ||
        provider.model_names.some((model) => checkLLMSupportsImageInput(model))
    );

    if (!hasImageCompatibleModel) {
      result.assistants = result.assistants.filter(
        (assistant) =>
          !assistant.tools.some(
            (tool) => tool.in_code_tool_id === "ImageGenerationTool"
          )
      );
    }
  }

  if (fetchOptions.includes("folders")) {
    const openedFoldersCookie = requestCookies.get("openedFolders");
    result.openedFolders = openedFoldersCookie
      ? JSON.parse(openedFoldersCookie.value)
      : {};
  }

  const defaultAssistantIdRaw = searchParams["assistantId"];
  result.defaultAssistantId = defaultAssistantIdRaw
    ? parseInt(defaultAssistantIdRaw)
    : undefined;

  const documentSidebarCookieInitialWidth = requestCookies.get(
    DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME
  );
  const sidebarToggled = requestCookies.get(SIDEBAR_TOGGLED_COOKIE_NAME);

  result.toggleSidebar = sidebarToggled
    ? sidebarToggled.value.toLowerCase() === "true"
    : NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN;

  result.finalDocumentSidebarInitialWidth = documentSidebarCookieInitialWidth
    ? parseInt(documentSidebarCookieInitialWidth.value)
    : undefined;

  if (fetchOptions.includes("ccPairs") && result.ccPairs) {
    const hasAnyConnectors = result.ccPairs.length > 0;
    result.shouldShowWelcomeModal =
      !hasCompletedWelcomeFlowSS(requestCookies) &&
      !hasAnyConnectors &&
      (!user || user.role === "admin");

    result.shouldDisplaySourcesIncompleteModal =
      hasAnyConnectors &&
      !result.shouldShowWelcomeModal &&
      !result.ccPairs.some((ccPair) => ccPair.has_successful_run) &&
      (!user || user.role === "admin");
  }

  return result;
}
