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
import { FullEmbeddingModelResponse } from "@/components/embedding/interfaces";
import { Settings } from "@/app/admin/settings/interfaces";
import { fetchLLMProvidersSS } from "@/lib/llm/fetchLLMs";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { Folder } from "@/app/chat/folders/interfaces";
import { cookies, headers } from "next/headers";
import {
  SIDEBAR_TOGGLED_COOKIE_NAME,
  DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME,
} from "@/components/resizable/constants";
import { hasCompletedWelcomeFlowSS } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN } from "../constants";
import { redirect } from "next/navigation";

interface FetchChatDataResult {
  user: User | null;
  chatSessions: ChatSession[];
  ccPairs: CCPairBasicInfo[];
  availableSources: ValidSources[];
  documentSets: DocumentSet[];
  tags: Tag[];
  llmProviders: LLMProviderDescriptor[];
  folders: Folder[];
  openedFolders: Record<string, boolean>;
  defaultAssistantId?: number;
  toggleSidebar: boolean;
  finalDocumentSidebarInitialWidth?: number;
  shouldShowWelcomeModal: boolean;
}

export async function fetchChatData(searchParams: {
  [key: string]: string;
}): Promise<FetchChatDataResult | { redirect: string }> {
  const requestCookies = await cookies();
  const tasks = [
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
    fetchSS("/manage/connector-status"),
    fetchSS("/manage/document-set"),
    fetchSS("/chat/get-user-chat-sessions"),
    fetchSS("/query/valid-tags"),
    fetchLLMProvidersSS(),
    fetchSS("/folder"),
  ];

  let results: (
    | User
    | Response
    | AuthTypeMetadata
    | FullEmbeddingModelResponse
    | Settings
    | LLMProviderDescriptor[]
    | [Persona[], string | null]
    | null
  )[] = [null, null, null, null, null, null, null, null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }

  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;
  const ccPairsResponse = results[2] as Response | null;
  const documentSetsResponse = results[3] as Response | null;

  const chatSessionsResponse = results[4] as Response | null;

  const tagsResponse = results[5] as Response | null;
  const llmProviders = (results[6] || []) as LLMProviderDescriptor[];
  const foldersResponse = results[7] as Response | null;

  const authDisabled = authTypeMetadata?.authType === "disabled";

  // TODO Validate need
  if (!authDisabled && !user) {
    const headersList = await headers();
    const fullUrl = headersList.get("x-url") || "/chat";
    const searchParamsString = new URLSearchParams(
      searchParams as unknown as Record<string, string>
    ).toString();
    const redirectUrl = searchParamsString
      ? `${fullUrl}?${searchParamsString}`
      : fullUrl;

    return redirect(`/auth/login?next=${encodeURIComponent(redirectUrl)}`);
  }

  if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
    return { redirect: "/auth/waiting-on-verification" };
  }

  let ccPairs: CCPairBasicInfo[] = [];
  if (ccPairsResponse?.ok) {
    ccPairs = await ccPairsResponse.json();
  } else {
    console.log(`Failed to fetch connectors - ${ccPairsResponse?.status}`);
  }
  const availableSources: ValidSources[] = [];
  ccPairs.forEach((ccPair) => {
    if (!availableSources.includes(ccPair.source)) {
      availableSources.push(ccPair.source);
    }
  });

  let chatSessions: ChatSession[] = [];
  if (chatSessionsResponse?.ok) {
    chatSessions = (await chatSessionsResponse.json()).sessions;
  } else {
    console.log(
      `Failed to fetch chat sessions - ${chatSessionsResponse?.text()}`
    );
  }

  chatSessions.sort(
    (a, b) =>
      new Date(b.time_created).getTime() - new Date(a.time_created).getTime()
  );

  let documentSets: DocumentSet[] = [];
  if (documentSetsResponse?.ok) {
    documentSets = await documentSetsResponse.json();
  } else {
    console.log(
      `Failed to fetch document sets - ${documentSetsResponse?.status}`
    );
  }

  let tags: Tag[] = [];
  if (tagsResponse?.ok) {
    tags = (await tagsResponse.json()).tags;
  } else {
    console.log(`Failed to fetch tags - ${tagsResponse?.status}`);
  }

  const defaultAssistantIdRaw = searchParams["assistantId"];
  const defaultAssistantId = defaultAssistantIdRaw
    ? parseInt(defaultAssistantIdRaw)
    : undefined;

  const documentSidebarCookieInitialWidth = requestCookies.get(
    DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME
  );
  const sidebarToggled = requestCookies.get(SIDEBAR_TOGGLED_COOKIE_NAME);

  const toggleSidebar = sidebarToggled
    ? sidebarToggled.value.toLocaleLowerCase() == "true" || false
    : NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN;

  const finalDocumentSidebarInitialWidth = documentSidebarCookieInitialWidth
    ? parseInt(documentSidebarCookieInitialWidth.value)
    : undefined;

  const hasAnyConnectors = ccPairs.length > 0;
  const shouldShowWelcomeModal =
    !llmProviders.length &&
    !hasCompletedWelcomeFlowSS(requestCookies) &&
    !hasAnyConnectors &&
    (!user || user.role === "admin");

  // if no connectors are setup, only show personas that are pure
  // passthrough and don't do any retrieval

  let folders: Folder[] = [];
  if (foldersResponse?.ok) {
    folders = (await foldersResponse.json()).folders as Folder[];
  } else {
    console.log(`Failed to fetch folders - ${foldersResponse?.status}`);
  }

  const openedFoldersCookie = requestCookies.get("openedFolders");
  const openedFolders = openedFoldersCookie
    ? JSON.parse(openedFoldersCookie.value)
    : {};

  return {
    user,
    chatSessions,
    ccPairs,
    availableSources,
    documentSets,
    tags,
    llmProviders,
    folders,
    openedFolders,
    defaultAssistantId,
    finalDocumentSidebarInitialWidth,
    toggleSidebar,
    shouldShowWelcomeModal,
  };
}
