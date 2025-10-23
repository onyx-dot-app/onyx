"use client";

import Prism from "prismjs";

import { humanReadableFormat } from "@/lib/time";
import { BackendChatSession } from "../../interfaces";
import { processRawChatHistory } from "../../services/lib";
import { getLatestMessageChain } from "../../services/messageTree";
import HumanMessage from "../../message/HumanMessage";
import AIMessage from "../../message/messageComponents/AIMessage";
import { Callout } from "@/components/ui/callout";
import { useContext, useEffect, useState } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { OnyxInitializingLoader } from "@/components/OnyxInitializingLoader";
import { Persona } from "@/app/admin/assistants/interfaces";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import TextView from "@/components/chat/TextView";
import { DocumentResults } from "../../components/documentSidebar/DocumentResults";
import { Modal } from "@/components/Modal";
import FixedLogo from "@/components/logo/FixedLogo";
import Link from "next/link";

function BackToOnyxButton({
  documentSidebarVisible,
}: {
  documentSidebarVisible: boolean;
}) {
  const enterpriseSettings = useContext(SettingsContext)?.enterpriseSettings;

  return (
    <div className="absolute bottom-0 bg-background w-full flex border-t border-border py-4">
      <div className="mx-auto">
        <Link href="/chat">
          Back to {enterpriseSettings?.application_name || "Onyx Chat"}
        </Link>
      </div>
      <div
        style={{ transition: "width 0.30s ease-out" }}
        className={`
            flex-none 
            overflow-y-hidden 
            transition-all 
            duration-300 
            ease-in-out
            ${documentSidebarVisible ? "w-[400px]" : "w-[0px]"}
        `}
      ></div>
    </div>
  );
}

export function SharedChatDisplay({
  chatSession,
  persona,
}: {
  chatSession: BackendChatSession | null;
  persona: Persona;
}) {
  const settings = useContext(SettingsContext);
  const [documentSidebarVisible, setDocumentSidebarVisible] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  useEffect(() => {
    Prism.highlightAll();
    setIsReady(true);
  }, []);
  if (!chatSession) {
    return (
      <div className="min-h-full w-full">
        <div className="mx-auto w-fit pt-8">
          <Callout type="danger" title="Shared Chat Not Found">
            Did not find a shared chat with the specified ID.
          </Callout>
        </div>
        <BackToOnyxButton documentSidebarVisible={documentSidebarVisible} />
      </div>
    );
  }

  const messages = getLatestMessageChain(
    processRawChatHistory(chatSession.messages, chatSession.packets)
  );

  const firstMessage = messages[0];

  if (firstMessage === undefined) {
    return (
      <div className="min-h-full w-full">
        <div className="mx-auto w-fit pt-8">
          <Callout type="danger" title="Shared Chat Not Found">
            No messages found in shared chat.
          </Callout>
        </div>
        <BackToOnyxButton documentSidebarVisible={documentSidebarVisible} />
      </div>
    );
  }

  return (
    <>
      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}
      {documentSidebarVisible && settings?.isMobile && (
        <div className="md:hidden">
          <Modal noPadding noScroll>
            <DocumentResults
              isSharedChat={true}
              toggleDocumentSelection={() => {
                setDocumentSidebarVisible(true);
              }}
              selectedDocuments={[]}
              clearSelectedDocuments={() => {}}
              selectedDocumentTokens={0}
              maxTokens={0}
              setPresentingDocument={setPresentingDocument}
              modal={true}
              closeSidebar={() => {
                setDocumentSidebarVisible(false);
              }}
            />
          </Modal>
        </div>
      )}

      <div className="fixed inset-0 flex flex-col text-default">
        <div className="h-[100dvh] px-2 overflow-y-hidden">
          <div className="w-full h-[100dvh] flex flex-col overflow-hidden">
            {!settings?.isMobile && (
              <div
                style={{ transition: "width 0.30s ease-out" }}
                className={`
                  flex-none 
                  fixed
                  right-0
                  z-[1000]
                  bg-background
                  h-screen
                  transition-all
                  bg-opacity-80
                  duration-300
                  ease-in-out
                  bg-transparent
                  transition-all
                  bg-opacity-80
                  duration-300
                  ease-in-out
                  h-full
                  ${documentSidebarVisible ? "w-[400px]" : "w-[0px]"}
            `}
              >
                <DocumentResults
                  modal={false}
                  isSharedChat={true}
                  toggleDocumentSelection={() => {
                    setDocumentSidebarVisible(true);
                  }}
                  clearSelectedDocuments={() => {}}
                  selectedDocumentTokens={0}
                  maxTokens={0}
                  setPresentingDocument={setPresentingDocument}
                  closeSidebar={() => {
                    setDocumentSidebarVisible(false);
                  }}
                  selectedDocuments={[]}
                />
              </div>
            )}

            <div className="flex w-full overflow-hidden overflow-y-scroll">
              <div className="w-full h-full   flex-col flex max-w-message-max mx-auto">
                <div className="fixed z-10 w-full ">
                  <div className="bg-background relative px-5 pt-4 w-full">
                    <h1 className="text-3xl text-strong font-bold">
                      {chatSession.description || `Unnamed Chat`}
                    </h1>
                    <p className=" text-text-darker">
                      {humanReadableFormat(chatSession.time_created)}
                    </p>
                    <div
                      className={`
                      h-full absolute top-0  z-10 w-full sm:w-[90%] lg:w-[70%]
                      bg-gradient-to-b via-50% z-[-1] from-background via-background to-background/10 flex
                      transition-all duration-300 ease-in-out
                      ${
                        documentSidebarVisible
                          ? "left-[200px] transform -translate-x-[calc(50%+100px)]"
                          : "left-1/2 transform -translate-x-1/2"
                      }
                    `}
                    />
                  </div>
                </div>
                {isReady ? (
                  <div className="w-full pt-24 pb-16">
                    {messages.map((message, i) => {
                      if (message.type === "user") {
                        return (
                          <HumanMessage
                            shared
                            key={message.messageId}
                            content={message.message}
                            files={message.files}
                          />
                        );
                      } else if (message.type === "assistant") {
                        return (
                          <AIMessage
                            key={message.messageId}
                            rawPackets={message.packets}
                            chatState={{
                              handleFeedback: () => {}, // No feedback in shared chat
                              assistant: persona,
                              docs: message.documents,
                              userFiles: [],
                              citations: message.citations,
                              setPresentingDocument: setPresentingDocument,
                              regenerate: undefined, // No regeneration in shared chat
                              overriddenModel: message.overridden_model,
                            }}
                            nodeId={message.nodeId}
                            llmManager={null}
                            otherMessagesCanSwitchTo={undefined}
                            onMessageSelection={undefined}
                          />
                        );
                      } else {
                        // Error message case
                        return (
                          <div
                            key={message.messageId}
                            className="py-5 ml-4 lg:px-5"
                          >
                            <div className="mx-auto w-[90%] max-w-message-max">
                              <p className="text-red-700 text-sm my-auto">
                                {message.message}
                              </p>
                            </div>
                          </div>
                        );
                      }
                    })}
                  </div>
                ) : (
                  <div className="grow flex-0 h-screen w-full flex items-center justify-center">
                    <div className="mb-[33vh]">
                      <OnyxInitializingLoader />
                    </div>
                  </div>
                )}
              </div>
              {!settings?.isMobile && (
                <div
                  style={{ transition: "width 0.30s ease-out" }}
                  className={`
                          flex-none 
                          overflow-y-hidden 
                          transition-all 
                          duration-300 
                          ease-in-out
                          ${documentSidebarVisible ? "w-[400px]" : "w-[0px]"}
                      `}
                ></div>
              )}
            </div>
          </div>

          <FixedLogo backgroundToggled={false} />
          <BackToOnyxButton documentSidebarVisible={documentSidebarVisible} />
        </div>
      </div>
    </>
  );
}
