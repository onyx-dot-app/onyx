import {
  AuthTypeMetadata,
  getAuthTypeMetadataSS,
  getCurrentUserSS,
} from "@/lib/userSS";
import { redirect } from "next/navigation";
import { fetchSS } from "@/lib/utilsSS";
import {
  CCPairBasicInfo,
  DocumentSet,
  Tag,
  User,
  ValidSources,
} from "@/lib/types";
import { ChatSession } from "./interfaces";
import { unstable_noStore as noStore } from "next/cache";
import { Persona } from "../admin/assistants/interfaces";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import {
  WelcomeModal,
  hasCompletedWelcomeFlowSS,
} from "@/components/initialSetup/welcome/WelcomeModalWrapper";
import { ApiKeyModal } from "@/components/llm/ApiKeyModal";
import { cookies } from "next/headers";
import { DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME } from "@/components/resizable/contants";
import { personaComparator } from "../admin/assistants/lib";
import { ChatPage } from "./ChatPage";
import { FullEmbeddingModelResponse } from "../admin/models/embedding/embeddingModels";
import { NoCompleteSourcesModal } from "@/components/initialSetup/search/NoCompleteSourceModal";
import { Settings } from "../admin/settings/interfaces";
import { SIDEBAR_TAB_COOKIE, Tabs } from "./sessionSidebar/constants";
import { fetchLLMProvidersSS } from "@/lib/llm/fetchLLMs";
import { LLMProviderDescriptor } from "../admin/models/llm/interfaces";
import { UserDisclaimerModal } from "@/components/search/UserDisclaimerModal";

export default async function Page({
  searchParams,
}: {
  searchParams: { [key: string]: string };
}) {
  noStore();

  const tasks = [
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
    fetchSS("/manage/indexing-status"),
    fetchSS("/manage/document-set"),
    fetchSS("/persona?include_default=true"),
    fetchSS("/chat/get-user-chat-sessions"),
    fetchSS("/query/valid-tags"),
    fetchLLMProvidersSS(),
    fetchSS("/eea_config/get_eea_config"),
  ];

  // catch cases where the backend is completely unreachable here
  // without try / catch, will just raise an exception and the page
  // will not render
  let results: (
    | User
    | Response
    | AuthTypeMetadata
    | FullEmbeddingModelResponse
    | Settings
    | LLMProviderDescriptor[]
    | null
  )[] = [null, null, null, null, null, null, null, null, null, null];
  try {
    results = await Promise.all(tasks);
  } catch (e) {
    console.log(`Some fetch failed for the main search page - ${e}`);
  }
  const authTypeMetadata = results[0] as AuthTypeMetadata | null;
  const user = results[1] as User | null;
  const ccPairsResponse = results[2] as Response | null;
  const documentSetsResponse = results[3] as Response | null;
  const personasResponse = results[4] as Response | null;
  const chatSessionsResponse = results[5] as Response | null;
  const tagsResponse = results[6] as Response | null;
  const llmProviders = (results[7] || []) as LLMProviderDescriptor[];
  const EEAConfigResponse = results[8] as Response | null;

  let disclaimerTitle = "";
  let disclaimerText = "";
  if (EEAConfigResponse?.ok) {
    const eea_config = await EEAConfigResponse.json();
    let conf = {"disclaimer":{"disclaimer_title":"", "disclaimer_text": ""}}
    try{
      conf = JSON.parse(eea_config?.config)
    }
    catch(e){
      console.log("error parsing eea_conf")
    }
    disclaimerTitle = conf?.disclaimer?.disclaimer_title || "";
    disclaimerText = conf?.disclaimer?.disclaimer_text || "";
  }

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
  // Larger ID -> created later
  chatSessions.sort((a, b) => (a.id > b.id ? -1 : 1));

  let documentSets: DocumentSet[] = [];
  if (documentSetsResponse?.ok) {
    documentSets = await documentSetsResponse.json();
  } else {
    console.log(
      `Failed to fetch document sets - ${documentSetsResponse?.status}`
    );
  }

  const defaultModel = llmProviders[0].default_model_name || "default model";

  let personas: Persona[] = [];
  if (personasResponse?.ok) {
    personas = await personasResponse.json();
  } else {
    console.log(`Failed to fetch personas - ${personasResponse?.status}`);
  }
  // remove those marked as hidden by an admin
  personas = personas.filter((persona) => persona.is_visible);
  // sort them in priority order
  personas.sort(personaComparator);

  let tags: Tag[] = [];
  if (tagsResponse?.ok) {
    tags = (await tagsResponse.json()).tags;
  } else {
    console.log(`Failed to fetch tags - ${tagsResponse?.status}`);
  }

  const defaultPersonaIdRaw = searchParams["assistantId"];
  const defaultPersonaId = defaultPersonaIdRaw
    ? parseInt(defaultPersonaIdRaw)
    : undefined;

  const documentSidebarCookieInitialWidth = cookies().get(
    DOCUMENT_SIDEBAR_WIDTH_COOKIE_NAME
  );
  const finalDocumentSidebarInitialWidth = documentSidebarCookieInitialWidth
    ? parseInt(documentSidebarCookieInitialWidth.value)
    : undefined;

  const defaultSidebarTab = cookies().get(SIDEBAR_TAB_COOKIE)?.value as
    | Tabs
    | undefined;

  const hasAnyConnectors = ccPairs.length > 0;
  const shouldShowWelcomeModal =
    !hasCompletedWelcomeFlowSS() &&
    !hasAnyConnectors &&
    (!user || user.role === "admin");
  const shouldDisplaySourcesIncompleteModal =
    hasAnyConnectors &&
    !shouldShowWelcomeModal &&
    !ccPairs.some(
      (ccPair) => ccPair.has_successful_run && ccPair.docs_indexed > 0
    );

  // if no connectors are setup, only show personas that are pure
  // passthrough and don't do any retrieval
  if (!hasAnyConnectors) {
    personas = personas.filter((persona) => persona.num_chunks === 0);
  }

  return (
    <>
      <UserDisclaimerModal disclaimerText={disclaimerText} disclaimerTitle={disclaimerTitle}/>

      <InstantSSRAutoRefresh />

      {shouldShowWelcomeModal && <WelcomeModal user={user} />}
      {!shouldShowWelcomeModal && !shouldDisplaySourcesIncompleteModal && (
        <ApiKeyModal user={user} />
      )}
      {shouldDisplaySourcesIncompleteModal && (
        <NoCompleteSourcesModal ccPairs={ccPairs} />
      )}

      <ChatPage
        user={user}
        chatSessions={chatSessions}
        availableSources={availableSources}
        availableDocumentSets={documentSets}
        availablePersonas={personas}
        availableTags={tags}
        llmProviders={llmProviders}
        defaultSelectedPersonaId={defaultPersonaId}
        documentSidebarInitialWidth={finalDocumentSidebarInitialWidth}
        defaultSidebarTab={defaultSidebarTab}
        defaultModel={defaultModel}
      />
    </>
  );
}
