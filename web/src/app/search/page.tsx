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
import {
  WelcomeModal,
  hasCompletedWelcomeFlowSS,
} from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { unstable_noStore as noStore } from "next/cache";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { personaComparator } from "../admin/assistants/lib";
import { FullEmbeddingModelResponse } from "@/components/embedding/interfaces";
import { NoSourcesModal } from "@/components/initialSetup/search/NoSourcesModal";
import { NoCompleteSourcesModal } from "@/components/initialSetup/search/NoCompleteSourceModal";
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
import { ProviderContextProvider } from "@/components/chat_search/ProviderContext";

export default async function Home() {
  // Disable caching so we always get the up to date connector / document set / persona info
  // importantly, this prevents users from adding a connector, going back to the main page,
  // and then getting hit with a "No Connectors" popup
  noStore();

  const tasks = [
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
    fetchSS("/manage/indexing-status"),
    fetchSS("/manage/document-set"),
    fetchAssistantsSS(),
    fetchSS("/query/valid-tags"),
    fetchSS("/search-settings/get-all-search-settings"),
    fetchSS("/query/user-searches"),
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
  const embeddingModelResponse = results[6] as Response | null;
  
  const config = await fetchEEASettings();
  
  const {
    disclaimerTitle,
    disclaimerText
  } = config;
  
  const queryResponse = results[7] as Response | null;

  const authDisabled = authTypeMetadata?.authType === "disabled";
  if (!authDisabled && !user) {
    return redirect("/auth/login");
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

  const embeddingModelVersionInfo =
    embeddingModelResponse && embeddingModelResponse.ok
      ? ((await embeddingModelResponse.json()) as FullEmbeddingModelResponse)
      : null;

  const currentEmbeddingModelName =
    embeddingModelVersionInfo?.current_model_name;
  const nextEmbeddingModelName =
    embeddingModelVersionInfo?.secondary_model_name;

  // needs to be done in a non-client side component due to nextjs
  const storedSearchType = cookies().get("searchType")?.value as
    | string
    | undefined;
  let searchTypeDefault: SearchType =
    storedSearchType !== undefined &&
    SearchType.hasOwnProperty(storedSearchType)
      ? (storedSearchType as SearchType)
      : SearchType.SEMANTIC; // default to semantic

  const hasAnyConnectors = ccPairs.length > 0;
  const shouldShowWelcomeModal =
    !hasCompletedWelcomeFlowSS() &&
    !hasAnyConnectors &&
    (!user || user.role === "admin");

  const shouldDisplayNoSourcesModal =
    (!user || user.role === "admin") &&
    ccPairs.length === 0 &&
    !shouldShowWelcomeModal;

  const shouldDisplaySourcesIncompleteModal =
    !ccPairs.some(
      (ccPair) => ccPair.has_successful_run && ccPair.docs_indexed > 0
    ) &&
    !shouldDisplayNoSourcesModal &&
    !shouldShowWelcomeModal &&
    (!user || user.role == "admin");

  const sidebarToggled = cookies().get(SIDEBAR_TOGGLED_COOKIE_NAME);
  const agenticSearchToggle = cookies().get(AGENTIC_SEARCH_TYPE_COOKIE_NAME);

  const toggleSidebar = sidebarToggled
    ? sidebarToggled.value.toLocaleLowerCase() == "true" || false
    : NEXT_PUBLIC_DEFAULT_SIDEBAR_OPEN;

  const agenticSearchEnabled = agenticSearchToggle
    ? agenticSearchToggle.value.toLocaleLowerCase() == "true" || false
    : false;

  return (
    <>
      <HealthCheckBanner />
      {shouldShowWelcomeModal && <WelcomeModal user={user} />}
      <InstantSSRAutoRefresh />

      {shouldDisplayNoSourcesModal && <NoSourcesModal />}

      {shouldDisplaySourcesIncompleteModal && (
        <NoCompleteSourcesModal ccPairs={ccPairs} />
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
