"use client";

import { useMemo, useReducer, useState } from "react";
import { humanReadableFormat } from "@opal/time";
import { BackendChatSession } from "@/app/app/types";
import { processRawChatHistory } from "@/app/app/services/lib";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import HumanMessage from "@/app/app/message/HumanMessage";
import AgentResultsDivider from "@/app/app/message/AgentResultsDivider";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import MultiModelResponseView from "@/app/app/message/MultiModelResponseView";
import { getMultiModelResponses } from "@/app/app/message/multiModel";
import { useLanguageModels } from "@/lib/languageModels/hooks";
import { buildModelProviderLookup } from "@/lib/languageModels/options";
import OnyxInitializingLoader from "@/components/OnyxInitializingLoader";
import { IllustrationContent, RootLayout, Section } from "@opal/layouts";
import SvgNotFound from "@opal/illustrations/not-found";
import { Button, Text, useCreateModal } from "@opal/components";
import { Agent } from "@/lib/agents/types";
import { useAppPosition } from "@/lib/navigation/hooks";
import { MinimalOnyxDocument } from "@/lib/search/types";
import PreviewModal from "@/sections/modals/PreviewModal";
import useOnMount from "@/hooks/useOnMount";
import SharedAppInputBar from "@/sections/input/SharedAppInputBar";
import {
  addLoadedPublishedFiles,
  NO_LOADED_PUBLISHED_FILES,
} from "@/lib/chat/publishedFiles";
import { usePublishedFiles } from "@/lib/chat/hooks";
import { PublishedFilesButton } from "@/sections/chat/PublishedFileViews";
import { ChatRightPanel } from "@/sections/chat/ChatRightPanel";
import {
  INITIAL_RIGHT_PANEL,
  rightPanelReducer,
  showsFiles,
} from "@/lib/chat/rightPanel";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import { PublishedFileOpenerContext } from "@/sections/chat/PublishedFileCards";
import { useLocale, useTranslations } from "next-intl";

export interface SharedChatDisplayProps {
  chatSession: BackendChatSession | null;
  persona: Agent;
}

export default function SharedChatDisplay({
  chatSession,
  persona,
}: SharedChatDisplayProps) {
  const t = useTranslations("chat.sharedChat");
  const locale = useLocale();
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);
  const previewModal = useCreateModal();
  const presentDocument = (document: MinimalOnyxDocument) => {
    setPresentingDocument(document);
    previewModal.toggle(true);
  };
  // The page keeps the panel's state: a shared chat has no chat store entry
  const [rightPanel, dispatchRightPanel] = useReducer(
    rightPanelReducer,
    INITIAL_RIGHT_PANEL
  );

  // A shared chat has no live publishes: its load's list, or without one
  // its packets, gives the files
  const chat = useMemo(
    () =>
      chatSession && {
        messageTree: processRawChatHistory(
          chatSession.messages,
          chatSession.packets
        ),
        loadedPublishedFiles: addLoadedPublishedFiles(
          NO_LOADED_PUBLISHED_FILES,
          chatSession
        ),
      },
    [chatSession]
  );
  const { files: publishedFiles, publishIndex } = usePublishedFiles(chat);

  const isMounted = useOnMount();
  const appPosition = useAppPosition();

  // The shared viewer is authenticated, so the user-facing provider list is
  // available for resolving each model's provider icon, same as the live view.
  const { llmProviders } = useLanguageModels();
  const modelProviderLookup = useMemo(
    () => buildModelProviderLookup(llmProviders),
    [llmProviders]
  );

  if (!chatSession || !chat) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center">
        <Section flexDirection="column" alignItems="center" gap={4}>
          <IllustrationContent
            illustration={SvgNotFound}
            title={t("notFound.title")}
            description={t("notFound.description")}
          />
          <Button {...appPosition.linkToNewSession()} prominence="secondary">
            {t("newChatButton.label")}
          </Button>
        </Section>
      </div>
    );
  }

  const { messageTree } = chat;
  const messages = getLatestMessageChain(messageTree);

  const firstMessage = messages[0];
  const openPublishedFile = (file: PublishedFile) =>
    dispatchRightPanel({ type: "openFile", file });

  if (firstMessage === undefined) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center">
        <Section flexDirection="column" alignItems="center" gap={4}>
          <IllustrationContent
            illustration={SvgNotFound}
            title={t("notFound.title")}
            description={t("emptyChat.description")}
          />
          <Button {...appPosition.linkToNewSession()} prominence="secondary">
            {t("newChatButton.label")}
          </Button>
        </Section>
      </div>
    );
  }

  return (
    <PublishedFileOpenerContext.Provider value={openPublishedFile}>
      <previewModal.Provider>
        {presentingDocument && (
          <PreviewModal
            presentingDocument={presentingDocument}
            onClose={() => previewModal.toggle(false)}
          />
        )}
      </previewModal.Provider>

      {/* Always mounted, so a reply card opens its file whatever the Files
          list holds. A shared chat has no Sources view. */}
      <RootLayout.RightPanel>
        <ChatRightPanel
          sessionId={chatSession.chat_session_id}
          open={showsFiles(rightPanel)}
          state={rightPanel}
          dispatch={dispatchRightPanel}
          files={publishedFiles}
          publishIndex={publishIndex}
          sources={null}
          hasSources={false}
        />
      </RootLayout.RightPanel>

      <div className="flex flex-col h-full w-full overflow-hidden">
        <div className="flex-1 flex flex-col items-center overflow-y-auto">
          <div className="sticky top-0 z-10 flex items-center justify-between w-full bg-background-tint-01 px-8 py-4">
            <Text as="p" font="heading-headline" color="text-04">
              {chatSession.description || t("header.untitledChat.title")}
            </Text>
            <Section
              flexDirection="row"
              width="fit"
              height="fit"
              alignItems="center"
              gap={2}
            >
              <Section alignItems="end" gap={0} width="fit" height="fit">
                <Text as="p" font="secondary-body" color="text-03">
                  {t("header.sharedOn.text", {
                    date: humanReadableFormat(chatSession.time_created, locale),
                  })}
                </Text>
                {chatSession.owner_name && (
                  <Text as="p" font="secondary-body" color="text-03">
                    {t("header.owner.text", { name: chatSession.owner_name })}
                  </Text>
                )}
              </Section>
              {publishedFiles.length > 0 && (
                <PublishedFilesButton
                  pressed={showsFiles(rightPanel)}
                  onClick={() => dispatchRightPanel({ type: "toggleFiles" })}
                />
              )}
            </Section>
          </div>

          {isMounted ? (
            <div className="w-full flex flex-col items-center">
              {messages.map((message, i) => {
                if (message.type === "user") {
                  const multiModelResponses = getMultiModelResponses(
                    message,
                    messageTree,
                    modelProviderLookup
                  );
                  return (
                    <div
                      key={message.messageId}
                      className="w-full flex flex-col items-center"
                    >
                      <div className="w-[min(50rem,100%)]">
                        <HumanMessage
                          content={message.message}
                          files={message.files}
                          nodeId={message.nodeId}
                        />
                      </div>
                      {/* Multi-model turns render every response side-by-side,
                          full width, mirroring the author's comparison. */}
                      {multiModelResponses && (
                        <div className="w-full px-4 pt-12">
                          <MultiModelResponseView
                            responses={multiModelResponses}
                            chatState={{
                              agent: persona,
                              docs: [],
                              citations: undefined,
                              setPresentingDocument: presentDocument,
                            }}
                            llmManager={null}
                            parentMessage={message}
                            readOnly
                          />
                        </div>
                      )}
                    </div>
                  );
                }

                if (message.type === "agent_results") {
                  return (
                    <div
                      key={message.messageId}
                      className="w-[min(50rem,100%)]"
                    >
                      <AgentResultsDivider />
                    </div>
                  );
                }

                // Non-user (assistant or error): skip the single child the
                // chain surfaced when its parent is a multi-model turn. The
                // panels already render every response, including failures.
                const previousMessage = i !== 0 ? messages[i - 1] : null;
                if (
                  previousMessage?.type === "user" &&
                  getMultiModelResponses(
                    previousMessage,
                    messageTree,
                    modelProviderLookup
                  )
                ) {
                  return null;
                }

                if (message.type === "assistant" || message.type === "error") {
                  return (
                    <div
                      key={message.messageId}
                      className="w-[min(50rem,100%)]"
                    >
                      {(message.type !== "error" ||
                        message.packets.length > 0) && (
                        <AgentMessage
                          rawPackets={message.packets}
                          chatState={{
                            agent: persona,
                            docs: message.documents,
                            citations: message.citations,
                            setPresentingDocument: presentDocument,
                            // Shared payload carries the model as `modelDisplayName`,
                            // not `overridden_model`. Surface it in the read-only footer.
                            overriddenModel:
                              message.modelDisplayName ?? undefined,
                            overriddenModelProvider: message.modelDisplayName
                              ? modelProviderLookup.get(
                                  message.modelDisplayName
                                )
                              : undefined,
                          }}
                          nodeId={message.nodeId}
                          llmManager={null}
                          otherMessagesCanSwitchTo={undefined}
                          onMessageSelection={undefined}
                          hideFooter={message.type === "error"}
                          disableTTS={message.type === "error"}
                        />
                      )}
                      {message.type === "error" && (
                        <ErrorBanner
                          error={message.errorMessage ?? ""}
                          errorCode={message.errorCode ?? undefined}
                          isRetryable={message.isRetryable}
                          details={message.errorDetails ?? undefined}
                        />
                      )}
                    </div>
                  );
                }

                return null;
              })}
            </div>
          ) : (
            <div className="h-full w-full flex items-center justify-center">
              <OnyxInitializingLoader />
            </div>
          )}
        </div>

        <div className="w-full max-w-200 mx-auto px-4 pb-4">
          <SharedAppInputBar />
        </div>
      </div>
    </PublishedFileOpenerContext.Provider>
  );
}
