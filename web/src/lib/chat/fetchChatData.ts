import { fetchSS } from "@/lib/utilsSS";
import { requireAuth } from "@/lib/auth/requireAuth";
import {
  CCPairBasicInfo,
  DocumentSetSummary,
  Tag,
  User,
  ValidSources,
} from "@/lib/types";
import { ChatSession, InputPrompt } from "@/app/chat/interfaces";
import { Persona } from "@/app/admin/assistants/interfaces";
import { FullEmbeddingModelResponse } from "@/components/embedding/interfaces";
import { Settings } from "@/app/admin/settings/interfaces";
import { fetchLLMProvidersSS } from "@/lib/llm/fetchLLMs";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { cookies, headers } from "next/headers";
import {
  SIDEBAR_TOGGLED_COOKIE_NAME,
  DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME,
  PRO_SEARCH_TOGGLED_COOKIE_NAME,
} from "@/components/resizable/constants";
import { hasCompletedWelcomeFlowSS } from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import {
  NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN,
  NEXT_PUBLIC_ENABLE_CHROME_EXTENSION,
} from "../constants";
import { ToolSnapshot } from "../tools/interfaces";
import { fetchToolsSS } from "../tools/fetchTools";
import { Project } from "@/app/chat/projects/projectsService";

interface FetchChatDataResult {
  user: User | null;
  chatSessions: ChatSession[];
  ccPairs: CCPairBasicInfo[];
  availableSources: ValidSources[];
  documentSets: DocumentSetSummary[];
  tags: Tag[];
  llmProviders: LLMProviderDescriptor[];
  availableTools: ToolSnapshot[];
  defaultAssistantId?: number;
  sidebarInitiallyVisible: boolean;
  finalDocumentSidebarInitialWidth?: number;
  shouldShowWelcomeModal: boolean;
  inputPrompts: InputPrompt[];
  proSearchToggled: boolean;
  projects: Project[];
}

export async function fetchChatData(searchParams: {
  [key: string]: string;
}): Promise<FetchChatDataResult | { redirect: string }> {
  const requestCookies = await cookies();

  // STEP 1: Check authentication FIRST (before any protected resources)
  const authResult = await requireAuth();
  const { user, authTypeMetadata } = authResult;
  const authDisabled = authTypeMetadata?.authType === "disabled";

  // STEP 2: Handle authentication redirects with special cases
  if (authResult.redirect && !authDisabled) {
    // Special handling for chrome extension mode and login loop prevention
    const headersList = await headers();
    const fullUrl = headersList.get("x-url") || "/chat";

    // Check the referrer to prevent redirect loops
    const referrer = headersList.get("referer") || "";
    const isComingFromLogin = referrer.includes("/auth/login");

    // Also check for the from=login query parameter
    const isRedirectedFromLogin = searchParams["from"] === "login";

    // Only redirect if we're not already coming from the login page
    // and chrome extension mode is not enabled
    if (
      !NEXT_PUBLIC_ENABLE_CHROME_EXTENSION &&
      !isComingFromLogin &&
      !isRedirectedFromLogin
    ) {
      // Build redirect URL with search params preserved
      const searchParamsString = new URLSearchParams(
        searchParams as unknown as Record<string, string>
      ).toString();
      const redirectUrl = searchParamsString
        ? `${fullUrl}?${searchParamsString}`
        : fullUrl;
      return {
        redirect: `/auth/login?next=${encodeURIComponent(redirectUrl)}`,
      };
    }
  }

  // STEP 3: ONLY NOW fetch protected resources (after auth is verified)
  const protectedTasks = [
    fetchSS("/manage/connector-status"),
    fetchSS("/manage/document-set"),
    fetchSS("/chat/get-user-chat-sessions"),
    fetchSS("/query/valid-tags"),
    fetchLLMProvidersSS(),
    fetchSS("/input_prompt?include_public=true"),
    fetchToolsSS(),
    fetchSS("/user/projects/"),
  ];

  let results: (Response | LLMProviderDescriptor[] | ToolSnapshot[] | null)[] =
    [];

  try {
    results = await Promise.all(protectedTasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }

  const ccPairsResponse = results[0] as Response | null;
  const documentSetsResponse = results[1] as Response | null;
  const chatSessionsResponse = results[2] as Response | null;
  const tagsResponse = results[3] as Response | null;
  const llmProviders = (results[4] || []) as LLMProviderDescriptor[];

  let inputPrompts: InputPrompt[] = [];
  if (results[5] instanceof Response && results[5].ok) {
    inputPrompts = await results[5].json();
  } else {
    console.log("Failed to fetch input prompts");
  }

  const availableTools = (results[6] || []) as ToolSnapshot[];

  let projects: Project[] = [];
  if (results[7] instanceof Response && results[7].ok) {
    projects = await results[7].json();
  } else {
    console.log("Failed to fetch projects");
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
      new Date(b.time_updated).getTime() - new Date(a.time_updated).getTime()
  );

  let documentSets: DocumentSetSummary[] = [];
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

  const proSearchToggled =
    requestCookies.get(PRO_SEARCH_TOGGLED_COOKIE_NAME)?.value.toLowerCase() ===
    "true";

  // IF user is an anoymous user, we don't want to show the sidebar (they have no access to chat history)
  const sidebarInitiallyVisible =
    !user?.is_anonymous_user &&
    (sidebarToggled
      ? sidebarToggled.value.toLocaleLowerCase() == "true" || false
      : NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN);

  sidebarToggled
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

  return {
    user,
    chatSessions,
    ccPairs,
    availableSources,
    documentSets,
    tags,
    llmProviders,
    availableTools,
    defaultAssistantId,
    finalDocumentSidebarInitialWidth,
    sidebarInitiallyVisible,
    shouldShowWelcomeModal,
    inputPrompts,
    proSearchToggled,
    projects,
  };
}
