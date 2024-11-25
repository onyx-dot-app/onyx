import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { fetchSS } from "@/lib/utilsSS";
import { CCPairBasicInfo, DocumentSet, Tag, User } from "@/lib/types";
import { cookies } from "next/headers";
import { SearchType } from "@/lib/search/interfaces";
import { Persona } from "../admin/assistants/interfaces";
import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { personaComparator } from "../admin/assistants/lib";
import { FullEmbeddingModelResponse } from "@/components/embedding/interfaces";
import { UserDisclaimerModal } from "@/components/search/UserDisclaimerModal";
import { fetchEEASettings } from "@/lib/eea/fetchEEASettings";

import { ChatPopup } from "../chat/ChatPopup";
import {
  FetchAssistantsResponse,
  fetchAssistantsSS,
} from "@/lib/assistants/fetchAssistantsSS";
import { ChatSession } from "../chat/interfaces";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "@/components/resizable/constants";
import {
  AGENTIC_SEARCH_TYPE_COOKIE_NAME,
  NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN,
  DISABLE_LLM_DOC_RELEVANCE,
} from "@/lib/constants";
import WrappedSearch from "./WrappedSearch";
import { SearchProvider } from "@/components/context/SearchContext";
import { fetchLLMProvidersSS } from "@/lib/llm/fetchLLMs";
import { LLMProviderDescriptor } from "../admin/configuration/llm/interfaces";
import { headers } from "next/headers";
import {
  hasCompletedWelcomeFlowSS,
  WelcomeModal,
} from "@/components/initialSetup/welcome/WelcomeModalWrapper";

export default async function Home(props: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const searchParams = await props.searchParams;
  // Disable caching so we always get the up to date connector / document set / persona info
  // importantly, this prevents users from adding a connector, going back to the main page,
  // and then getting hit with a "No Connectors" popup
  noStore();
  const requestCookies = await cookies();
  const tasks = [
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
    fetchSS("/manage/indexing-status"),
    fetchSS("/manage/document-set"),
    fetchAssistantsSS(),
    fetchSS("/query/valid-tags"),
    fetchSS("/query/user-searches"),
    fetchLLMProvidersSS(),
  ];

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let results: (
    | User
    | Response
    | AuthTypeMetadata
    | FullEmbeddingModelResponse
    | FetchAssistantsResponse
    | LLMProviderDescriptor[]
    | null
  )[] = [null, null, null, null, null, null, null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }
  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;
  const ccPairsResponse = results[2] as Response | null;
  const documentSetsResponse = results[3] as Response | null;
  const [initialAssistantsList, assistantsFetchError] =
    results[4] as FetchAssistantsResponse;
  const tagsResponse = results[5] as Response | null;
  const queryResponse = results[6] as Response | null;
  const llmProviders = (results[7] || []) as LLMProviderDescriptor[];
  
  const config = await fetchEEASettings();
  
  const {
    disclaimerTitle,
    disclaimerText
  } = config;

  const authDisabled = authTypeMetadata?.authType === "disabled";

  if (!authDisabled && !user) {
    const headersList = await headers();
    const fullUrl = headersList.get("x-url") || "/search";
    const searchParamsString = new URLSearchParams(
      searchParams as unknown as Record<string, string>
    ).toString();
    const redirectUrl = searchParamsString
      ? `${fullUrl}?${searchParamsString}`
      : fullUrl;
    return redirect(`/auth/login?next=${encodeURIComponent(redirectUrl)}`);
  }

  if (user && !user.is_verified && authTypeMetadata?.requiresVerification) {
    return redirect("/auth/waiting-on-verification");
  }

  let ccPairs: CCPairBasicInfo[] = [];
  if (ccPairsResponse?.ok) {
    ccPairs = await ccPairsResponse.json();
  } else {
    console.log(`Failed to fetch connectors - ${ccPairsResponse?.status}`);
  }

  let documentSets: DocumentSet[] = [];
  if (documentSetsResponse?.ok) {
    documentSets = await documentSetsResponse.json();
  } else {
    console.log(
      `Failed to fetch document sets - ${documentSetsResponse?.status}`
    );
  }

  let querySessions: ChatSession[] = [];
  if (queryResponse?.ok) {
    querySessions = (await queryResponse.json()).sessions;
  } else {
    console.log(`Failed to fetch chat sessions - ${queryResponse?.text()}`);
  }

  let assistants: Persona[] = initialAssistantsList;
  if (assistantsFetchError) {
    console.log(`Failed to fetch assistants - ${assistantsFetchError}`);
  } else {
    // remove those marked as hidden by an admin
    assistants = assistants.filter((assistant) => assistant.is_visible);
    // hide personas with no retrieval
    assistants = assistants.filter((assistant) => assistant.num_chunks !== 0);
    // sort them in priority order
    assistants.sort(personaComparator);
  }

  let tags: Tag[] = [];
  if (tagsResponse?.ok) {
    tags = (await tagsResponse.json()).tags;
  } else {
    console.log(`Failed to fetch tags - ${tagsResponse?.status}`);
  }

  // needs to be done in a non-client side component due to nextjs
  const storedSearchType = requestCookies.get("searchType")?.value as
    | string
    | undefined;
  const searchTypeDefault: SearchType =
    storedSearchType !== undefined &&
    SearchType.hasOwnProperty(storedSearchType)
      ? (storedSearchType as SearchType)
      : SearchType.SEMANTIC; // default to semantic

  const hasAnyConnectors = ccPairs.length > 0;

  const shouldShowWelcomeModal =
    !llmProviders.length &&
    !hasCompletedWelcomeFlowSS(requestCookies) &&
    !hasAnyConnectors &&
    (!user || user.role === "admin");

  const shouldDisplayNoSourcesModal =
    (!user || user.role === "admin") &&
    ccPairs.length === 0 &&
    !shouldShowWelcomeModal;

  const sidebarToggled = requestCookies.get(SIDEBAR_TOGGLED_COOKIE_NAME);
  const agenticSearchToggle = requestCookies.get(
    AGENTIC_SEARCH_TYPE_COOKIE_NAME
  );

  const toggleSidebar = sidebarToggled
    ? sidebarToggled.value.toLocaleLowerCase() == "true" || false
    : NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN;

  const agenticSearchEnabled = agenticSearchToggle
    ? agenticSearchToggle.value.toLocaleLowerCase() == "true" || false
    : false;

  return (
    <>
      <HealthCheckBanner />
      <InstantSSRAutoRefresh />
      {shouldShowWelcomeModal && (
        <WelcomeModal user={user} requestCookies={requestCookies} />
      )}
      {/* ChatPopup is a custom popup that displays a admin-specified message on initial user visit. 
      Only used in the EE version of the app. */}
      <ChatPopup />

      <UserDisclaimerModal disclaimerText={disclaimerText} disclaimerTitle={disclaimerTitle}/>
      <SearchProvider
        value={{
          querySessions,
          ccPairs,
          documentSets,
          assistants,
          tags,
          agenticSearchEnabled,
          disabledAgentic: DISABLE_LLM_DOC_RELEVANCE,
          initiallyToggled: toggleSidebar,
          shouldShowWelcomeModal,
          shouldDisplayNoSources: shouldDisplayNoSourcesModal,
        }}
      >
        <WrappedSearch
          initiallyToggled={toggleSidebar}
          searchTypeDefault={searchTypeDefault}
        />
      </SearchProvider>
    </>
  );
}
