"use client";

import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { FullSearchBar } from "./SearchBar";
import { SearchResultsDisplay } from "./SearchResultsDisplay";
import { SourceSelector } from "./filtering/Filters";
import {
  Quote,
  SearchResponse,
  FlowType,
  SearchType,
  SearchDefaultOverrides,
  SearchRequestOverrides,
  ValidQuestionResponse,
  Relevance,
  SearchDanswerDocument,
  SourceMetadata,
} from "@/lib/search/interfaces";
import { searchRequestStreamed } from "@/lib/search/streamingQa";
import { CancellationToken, cancellable } from "@/lib/search/cancellable";
import { useFilters, useObjectState } from "@/lib/hooks";
import { Persona } from "@/app/admin/assistants/interfaces";
import { computeAvailableFilters } from "@/lib/filters";
import { useRouter, useSearchParams } from "next/navigation";
import { SettingsContext } from "../settings/SettingsProvider";
import { HistorySidebar } from "@/app/chat/sessionSidebar/HistorySidebar";
import { ChatSession, SearchSession } from "@/app/chat/interfaces";
import FunctionalHeader from "../chat_search/Header";
import { useSidebarVisibility } from "../chat_search/hooks";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "../resizable/constants";
import { AGENTIC_SEARCH_TYPE_COOKIE_NAME } from "@/lib/constants";
import Cookies from "js-cookie";
import FixedLogo from "@/app/chat/shared_chat_search/FixedLogo";
import { usePopup } from "../admin/connectors/Popup";
import { FeedbackType } from "@/app/chat/types";
import { FeedbackModal } from "@/app/chat/modal/FeedbackModal";
import { deleteChatSession, handleChatFeedback } from "@/app/chat/lib";
import SearchAnswer from "./SearchAnswer";
import { DeleteEntityModal } from "../modals/DeleteEntityModal";
import { ApiKeyModal } from "../llm/ApiKeyModal";
import { useSearchContext } from "../context/SearchContext";
import { useUser } from "../user/UserProvider";
import UnconfiguredProviderText from "../chat_search/UnconfiguredProviderText";
import { DateRangePickerValue } from "@/app/ee/admin/performance/DateRangeSelector";
import { Tag } from "@/lib/types";
import { isEqual } from "lodash";

export type searchState =
  | "input"
  | "searching"
  | "reading"
  | "analyzing"
  | "summarizing"
  | "generating"
  | "citing";

const SEARCH_DEFAULT_OVERRIDES_START: SearchDefaultOverrides = {
  forceDisplayQA: false,
  offset: 0,
};

interface SearchSectionProps {
  toggle: () => void;
  defaultSearchType: SearchType;
  toggledSidebar: boolean;
}

export const SearchSection = ({
  toggle,
  toggledSidebar,
  defaultSearchType,
}: SearchSectionProps) => {
  const {
    querySessions,
    ccPairs,
    documentSets,
    assistants,
    tags,
    shouldShowWelcomeModal,
    agenticSearchEnabled,
    disabledAgentic,
    shouldDisplayNoSources,
  } = useSearchContext();

  const [query, setQuery] = useState<string>("");
  const [comments, setComments] = useState<any>(null);
  const [contentEnriched, setContentEnriched] = useState(false);

  const [searchResponse, setSearchResponse] = useState<SearchResponse>({
    suggestedSearchType: null,
    suggestedFlowType: null,
    answer: null,
    quotes: null,
    documents: null,
    selectedDocIndices: null,
    error: null,
    messageId: null,
  });

  const [showApiKeyModal, setShowApiKeyModal] = useState(true);

  const [agentic, setAgentic] = useState(agenticSearchEnabled);

  const toggleAgentic = useCallback(() => {
    Cookies.set(
      AGENTIC_SEARCH_TYPE_COOKIE_NAME,
      String(!agentic).toLocaleLowerCase()
    );
    setAgentic((agentic) => !agentic);
  }, [agentic]);

  const toggleSidebar = useCallback(() => {
    Cookies.set(
      SIDEBAR_TOGGLED_COOKIE_NAME,
      String(!toggledSidebar).toLocaleLowerCase()
    ),
      {
        path: "/",
      };
    toggle();
  }, [toggledSidebar, toggle]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        switch (event.key.toLowerCase()) {
          case "/":
            toggleAgentic();
            break;
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [toggleAgentic]);

  const [isFetching, setIsFetching] = useState(false);

  // Search Type
  const selectedSearchType = defaultSearchType;

  // If knowledge assistant exists, use it. Otherwise, use first available assistant for search.
  const selectedPersona = assistants.find((assistant) => assistant.id === 0)
    ? 0
    : assistants[0]?.id;

  // Used for search state display
  const [analyzeStartTime, setAnalyzeStartTime] = useState<number>(0);

  // Filters
  const filterManager = useFilters();
  const availableSources = ccPairs.map((ccPair) => ccPair.source);
  const [finalAvailableSources, finalAvailableDocumentSets] =
    computeAvailableFilters({
      selectedPersona: assistants.find(
        (assistant) => assistant.id === selectedPersona
      ),
      availableSources: availableSources,
      availableDocumentSets: documentSets,
    });

  const searchParams = useSearchParams();
  const existingSearchessionId = searchParams.get("searchId");

  useEffect(() => {
    if (existingSearchessionId == null) {
      return;
    }
    function extractFirstMessageByType(
      chatSession: SearchSession,
      messageType: "user" | "assistant"
    ): string | null {
      const userMessage = chatSession?.messages.find(
        (msg) => msg.message_type === messageType
      );
      return userMessage ? userMessage.message : null;
    }

    async function initialSessionFetch() {
      const response = await fetch(
        `/api/query/search-session/${existingSearchessionId}`
      );
      const searchSession = (await response.json()) as SearchSession;
      const userMessage = extractFirstMessageByType(searchSession, "user");
      const assistantMessage = extractFirstMessageByType(
        searchSession,
        "assistant"
      );

      if (userMessage) {
        setQuery(userMessage);
        const danswerDocs: SearchResponse = {
          documents: searchSession.documents,
          suggestedSearchType: null,
          answer: assistantMessage || "Search response not found",
          quotes: null,
          selectedDocIndices: null,
          error: null,
          messageId: searchSession.messages[0].message_id,
          suggestedFlowType: null,
          additional_relevance: undefined,
        };

        setIsFetching(false);
        setFirstSearch(false);
        setSearchResponse(danswerDocs);
        setContentEnriched(true);
      }
    }
    initialSessionFetch();
  }, [existingSearchessionId]);

  // Overrides for default behavior that only last a single query
  const [defaultOverrides, setDefaultOverrides] =
    useState<SearchDefaultOverrides>(SEARCH_DEFAULT_OVERRIDES_START);

  const newSearchState = (
    currentSearchState: searchState,
    newSearchState: searchState
  ) => {
    if (currentSearchState != "input") {
      return newSearchState;
    }
    return "input";
  };

  // Helpers
  const initialSearchResponse: SearchResponse = {
    answer: null,
    quotes: null,
    documents: null,
    suggestedSearchType: null,
    suggestedFlowType: null,
    selectedDocIndices: null,
    error: null,
    messageId: null,
    additional_relevance: undefined,
  };
  // Streaming updates
  const updateCurrentAnswer = (answer: string) => {
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      answer,
    }));

    if (analyzeStartTime) {
      const elapsedTime = Date.now() - analyzeStartTime;
      const nextInterval = Math.ceil(elapsedTime / 1500) * 1500;
      setTimeout(() => {
        setSearchState((searchState) =>
          newSearchState(searchState, "generating")
        );
      }, nextInterval - elapsedTime);
    }
  };

  const updateQuotes = (quotes: Quote[]) => {
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      quotes,
    }));
    setSearchState((searchState) => "citing");
  };

  const updateDocs = (documents: SearchDanswerDocument[]) => {
    if (agentic) {
      setTimeout(() => {
        setSearchState((searchState) => newSearchState(searchState, "reading"));
      }, 1500);

      setTimeout(() => {
        setAnalyzeStartTime(Date.now());
        setSearchState((searchState) => {
          const newState = newSearchState(searchState, "analyzing");
          if (newState === "analyzing") {
            setAnalyzeStartTime(Date.now());
          }
          return newState;
        });
      }, 4500);
    }

    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      documents,
    }));
    if (disabledAgentic) {
      setIsFetching(false);
      setSearchState((searchState) => "citing");
    }
    if (documents.length == 0) {
      setSearchState("input");
    }
  };
  const updateSuggestedSearchType = (suggestedSearchType: SearchType) =>
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      suggestedSearchType,
    }));
  const updateSuggestedFlowType = (suggestedFlowType: FlowType) =>
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      suggestedFlowType,
    }));
  const updateSelectedDocIndices = (docIndices: number[]) =>
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      selectedDocIndices: docIndices,
    }));
  const updateError = (error: FlowType) => {
    resetInput(true);

    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      error,
    }));
  };
  const updateMessageAndThreadId = (
    messageId: number,
    chat_session_id: string
  ) => {
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      messageId,
    }));
    router.refresh();
    setIsFetching(false);
    setSearchState((searchState) => "input");
  };

  const updateDocumentRelevance = (relevance: Relevance) => {
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      additional_relevance: relevance,
    }));

    setContentEnriched(true);

    setIsFetching(false);
    if (disabledAgentic) {
      setSearchState("input");
    } else {
      setSearchState("analyzing");
    }
  };

  const updateComments = (comments: any) => {
    setComments(comments);
  };

  const finishedSearching = () => {
    if (disabledAgentic) {
      setSearchState("input");
    }
  };
  const { user } = useUser();
  const [searchAnswerExpanded, setSearchAnswerExpanded] = useState(false);

  const resetInput = (finalized?: boolean) => {
    setSweep(false);
    setFirstSearch(false);
    setComments(null);
    setSearchState(finalized ? "input" : "searching");
    setSearchAnswerExpanded(false);
  };

  interface SearchDetails {
    query: string;
    sources: SourceMetadata[];
    agentic: boolean;
    documentSets: string[];
    timeRange: DateRangePickerValue | null;
    tags: Tag[];
    persona: Persona;
  }

  const [previousSearch, setPreviousSearch] = useState<null | SearchDetails>(
    null
  );
  const [agenticResults, setAgenticResults] = useState<boolean | null>(null);
  const currentSearch = (overrideMessage?: string): SearchDetails => {
    return {
      query: overrideMessage || query,
      sources: filterManager.selectedSources,
      agentic: agentic!,
      documentSets: filterManager.selectedDocumentSets,
      timeRange: filterManager.timeRange,
      tags: filterManager.selectedTags,
      persona: assistants.find(
        (assistant) => assistant.id === selectedPersona
      ) as Persona,
    };
  };
  const isSearchChanged = () => {
    return !isEqual(currentSearch(), previousSearch);
  };

  let lastSearchCancellationToken = useRef<CancellationToken | null>(null);
  const onSearch = async ({
    searchType,
    agentic,
    offset,
    overrideMessage,
  }: SearchRequestOverrides = {}) => {
    if ((overrideMessage || query) == "") {
      return;
    }
    setAgenticResults(agentic!);
    resetInput();
    setContentEnriched(false);

    if (lastSearchCancellationToken.current) {
      lastSearchCancellationToken.current.cancel();
    }
    lastSearchCancellationToken.current = new CancellationToken();

    setIsFetching(true);
    setSearchResponse(initialSearchResponse);

    setPreviousSearch(currentSearch(overrideMessage));

    const searchFnArgs = {
      query: overrideMessage || query,
      sources: filterManager.selectedSources,
      agentic: agentic,
      documentSets: filterManager.selectedDocumentSets,
      timeRange: filterManager.timeRange,
      tags: filterManager.selectedTags,
      persona: assistants.find(
        (assistant) => assistant.id === selectedPersona
      ) as Persona,
      updateCurrentAnswer: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateCurrentAnswer,
      }),
      updateQuotes: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateQuotes,
      }),
      updateDocs: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateDocs,
      }),
      updateSuggestedSearchType: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateSuggestedSearchType,
      }),
      updateSuggestedFlowType: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateSuggestedFlowType,
      }),
      updateSelectedDocIndices: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateSelectedDocIndices,
      }),
      updateError: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateError,
      }),
      updateMessageAndThreadId: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateMessageAndThreadId,
      }),
      updateDocStatus: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateMessageAndThreadId,
      }),
      updateDocumentRelevance: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateDocumentRelevance,
      }),
      updateComments: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: updateComments,
      }),
      finishedSearching: cancellable({
        cancellationToken: lastSearchCancellationToken.current,
        fn: finishedSearching,
      }),
      selectedSearchType: searchType ?? selectedSearchType,
      offset: offset ?? defaultOverrides.offset,
    };

    await Promise.all([searchRequestStreamed(searchFnArgs)]);
  };

  // handle redirect if search page is disabled
  // NOTE: this must be done here, in a client component since
  // settings are passed in via Context and therefore aren't
  // available in server-side components
  const router = useRouter();
  const settings = useContext(SettingsContext);
  if (settings?.settings?.search_page_enabled === false) {
    router.push("/chat");
  }
  const sidebarElementRef = useRef<HTMLDivElement>(null);
  const innerSidebarElementRef = useRef<HTMLDivElement>(null);
  const [showDocSidebar, setShowDocSidebar] = useState(false);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        switch (event.key.toLowerCase()) {
          case "e":
            event.preventDefault();
            toggleSidebar();
            break;
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [router, toggleSidebar]);

  useEffect(() => {
    if (settings?.isMobile) {
      router.push("/chat");
    }
  }, [settings?.isMobile, router]);

  const handleTransitionEnd = (e: React.TransitionEvent<HTMLDivElement>) => {
    if (e.propertyName === "opacity" && !firstSearch) {
      const target = e.target as HTMLDivElement;
      target.style.display = "none";
    }
  };
  const [sweep, setSweep] = useState(false);
  const performSweep = () => {
    setSweep((sweep) => !sweep);
  };
  const [firstSearch, setFirstSearch] = useState(true);
  const [searchState, setSearchState] = useState<searchState>("input");
  const [deletingChatSession, setDeletingChatSession] =
    useState<ChatSession | null>();

  const showDeleteModal = (chatSession: ChatSession) => {
    setDeletingChatSession(chatSession);
  };
  // Used to maintain a "time out" for history sidebar so our existing refs can have time to process change
  const [untoggled, setUntoggled] = useState(false);

  const explicitlyUntoggle = () => {
    setShowDocSidebar(false);

    setUntoggled(true);
    setTimeout(() => {
      setUntoggled(false);
    }, 200);
  };

  useSidebarVisibility({
    toggledSidebar,
    sidebarElementRef,
    showDocSidebar,
    setShowDocSidebar,
    mobile: settings?.isMobile,
  });
  const { answer, quotes, documents, error, messageId } = searchResponse;

  const dedupedQuotes: Quote[] = [];
  const seen = new Set<string>();
  if (quotes) {
    quotes.forEach((quote) => {
      if (!seen.has(quote.document_id)) {
        dedupedQuotes.push(quote);
        seen.add(quote.document_id);
      }
    });
  }
  const [currentFeedback, setCurrentFeedback] = useState<
    [FeedbackType, number] | null
  >(null);

  const onFeedback = async (
    messageId: number,
    feedbackType: FeedbackType,
    feedbackDetails: string,
    predefinedFeedback: string | undefined
  ) => {
    const response = await handleChatFeedback(
      messageId,
      feedbackType,
      feedbackDetails,
      predefinedFeedback
    );

    if (response.ok) {
      setPopup({
        message: "Thanks for your feedback!",
        type: "success",
      });
    } else {
      const responseJson = await response.json();
      const errorMsg = responseJson.detail || responseJson.message;
      setPopup({
        message: `Failed to submit feedback - ${errorMsg}`,
        type: "error",
      });
    }
  };

  const chatBannerPresent = settings?.enterpriseSettings?.custom_header_content;

  const { popup, setPopup } = usePopup();

  const shouldUseAgenticDisplay =
    agenticResults &&
    (searchResponse.documents || []).some(
      (document) =>
        searchResponse.additional_relevance &&
        searchResponse.additional_relevance[document.document_id] !== undefined
    );

  return (
    <>

      <div className="flex relative pr-[8px] h-full text-default">
        {popup}

        {!shouldDisplayNoSources &&
          showApiKeyModal &&
          !shouldShowWelcomeModal && (
            <ApiKeyModal
              setPopup={setPopup}
              hide={() => setShowApiKeyModal(false)}
            />
          )}

        {deletingChatSession && (
          <DeleteEntityModal
            entityType="search"
            entityName={deletingChatSession.name}
            onClose={() => setDeletingChatSession(null)}
            onSubmit={async () => {
              const response = await deleteChatSession(deletingChatSession.id);
              if (response.ok) {
                setDeletingChatSession(null);
                // go back to the main page
                router.push("/search");
              } else {
                const responseJson = await response.json();
                setPopup({ message: responseJson.detail, type: "error" });
              }
              router.refresh();
            }}
          />
        )}
        {currentFeedback && (
          <FeedbackModal
            feedbackType={currentFeedback[0]}
            onClose={() => setCurrentFeedback(null)}
            onSubmit={({ message, predefinedFeedback }) => {
              onFeedback(
                currentFeedback[1],
                currentFeedback[0],
                message,
                predefinedFeedback
              );
              setCurrentFeedback(null);
            }}
          />
        )}
        <div
          ref={sidebarElementRef}
          className={`
            flex-none 
            fixed
            left-0 
            z-30
            bg-background-100 
            h-screen
            transition-all 
            bg-opacity-80
            duration-300 
            ease-in-out
            ${
              !untoggled && (showDocSidebar || toggledSidebar)
                ? "opacity-100 w-[250px] translate-x-0"
                : "opacity-0 w-[200px] pointer-events-none -translate-x-10"
            }
          `}
        >
          <div className="w-full relative">
            <HistorySidebar
              showDeleteModal={showDeleteModal}
              explicitlyUntoggle={explicitlyUntoggle}
              reset={() => setQuery("")}
              page="search"
              ref={innerSidebarElementRef}
              toggleSidebar={toggleSidebar}
              toggled={toggledSidebar}
              existingChats={querySessions}
            />
          </div>
        </div>

        <div className="absolute include-scrollbar h-screen overflow-y-auto left-0 w-full top-0">
          <FunctionalHeader
            sidebarToggled={toggledSidebar}
            reset={() => setQuery("")}
            toggleSidebar={toggleSidebar}
            page="search"
          />
          <div className="w-full flex">
            <div
              style={{ transition: "width 0.30s ease-out" }}
              className={`
                  flex-none
                  overflow-y-hidden
                  bg-background-100
                  h-full
                  transition-all
                  bg-opacity-80
                  duration-300 
                  ease-in-out
                  ${toggledSidebar ? "w-[250px]" : "w-[0px]"}
                `}
            />

            {
              <div
                className={`desktop:px-24 w-full ${
                  chatBannerPresent && "mt-10"
                } pt-10 relative max-w-[2000px] xl:max-w-[1430px] mx-auto`}
              >
                <div className="absolute z-10 mobile:px-4 mobile:max-w-searchbar-max mobile:w-[90%] top-12 desktop:left-4 hidden 2xl:block mobile:left-1/2 mobile:transform mobile:-translate-x-1/2 desktop:w-52 3xl:w-64">
                  {!settings?.isMobile &&
                    (ccPairs.length > 0 || documentSets.length > 0) && (
                      <SourceSelector
                        {...filterManager}
                        showDocSidebar={toggledSidebar}
                        availableDocumentSets={finalAvailableDocumentSets}
                        existingSources={finalAvailableSources}
                        availableTags={tags}
                      />
                    )}
                </div>
                <div className="absolute left-0 hidden 2xl:block w-52 3xl:w-64"></div>
                <div className="max-w-searchbar-max w-[90%] mx-auto">
                  {settings?.isMobile && (
                    <div className="mt-6">
                      {!(agenticResults && isFetching) || disabledAgentic ? (
                        <SearchResultsDisplay
                          searchState={searchState}
                          disabledAgentic={disabledAgentic}
                          contentEnriched={contentEnriched}
                          comments={comments}
                          sweep={sweep}
                          agenticResults={agenticResults && !disabledAgentic}
                          performSweep={performSweep}
                          searchResponse={searchResponse}
                          isFetching={isFetching}
                          defaultOverrides={defaultOverrides}
                        />
                      ) : (
                        <></>
                      )}
                    </div>
                  )}
                  <div
                    className={`mobile:fixed mobile:left-1/2 mobile:transform mobile:-translate-x-1/2 mobile:max-w-search-bar-max mobile:w-[90%] mobile:z-100 mobile:bottom-12`}
                  >
                    <div
                      className={`transition-all duration-500 ease-in-out overflow-hidden 
                      ${
                        firstSearch
                          ? "opacity-100 max-h-[500px]"
                          : "opacity-0 max-h-0"
                      }`}
                      onTransitionEnd={handleTransitionEnd}
                    >
                      <div className="mt-48 mb-8 flex justify-center items-center">
                        <div className="w-message-xs 2xl:w-message-sm 3xl:w-message">
                          <div className="flex">
                            <div className="text-3xl font-bold font-strong text-strong mx-auto">
                              Unlock Knowledge
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <UnconfiguredProviderText
                      noSources={shouldDisplayNoSources}
                      showConfigureAPIKey={() => setShowApiKeyModal(true)}
                    />

                    <FullSearchBar
                      disabled={!isSearchChanged()}
                      toggleAgentic={
                        disabledAgentic ? undefined : toggleAgentic
                      }
                      showingSidebar={toggledSidebar}
                      agentic={agentic}
                      query={query}
                      setQuery={setQuery}
                      onSearch={async (agentic?: boolean) => {
                        setDefaultOverrides(SEARCH_DEFAULT_OVERRIDES_START);
                        await onSearch({ agentic, offset: 0 });
                      }}
                      finalAvailableDocumentSets={finalAvailableDocumentSets}
                      finalAvailableSources={finalAvailableSources}
                      filterManager={filterManager}
                      documentSets={documentSets}
                      ccPairs={ccPairs}
                      tags={tags}
                    />
                  </div>
                  {!firstSearch && (
                    <SearchAnswer
                      isFetching={isFetching}
                      dedupedQuotes={dedupedQuotes}
                      searchResponse={searchResponse}
                      setSearchAnswerExpanded={setSearchAnswerExpanded}
                      searchAnswerExpanded={searchAnswerExpanded}
                      setCurrentFeedback={setCurrentFeedback}
                      searchState={searchState}
                    />
                  )}

                  {!settings?.isMobile && (
                    <div className="mt-6">
                      {!(agenticResults && isFetching) || disabledAgentic ? (
                        <SearchResultsDisplay
                          searchState={searchState}
                          disabledAgentic={disabledAgentic}
                          contentEnriched={contentEnriched}
                          comments={comments}
                          sweep={sweep}
                          agenticResults={
                            shouldUseAgenticDisplay && !disabledAgentic
                          }
                          performSweep={performSweep}
                          searchResponse={searchResponse}
                          isFetching={isFetching}
                          defaultOverrides={defaultOverrides}
                        />
                      ) : (
                        <></>
                      )}
                    </div>
                  )}
                </div>
              </div>
            }
          </div>
        </div>
      </div>
      <FixedLogo backgroundToggled={toggledSidebar || showDocSidebar} />
    </>
  );
};
