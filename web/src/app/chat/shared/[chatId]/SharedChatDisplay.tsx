"use client";
import Prism from "prismjs";

import { humanReadableFormat } from "@/lib/time";
import { BackendChatSession } from "../../interfaces";
import {
  buildLatestMessageChain,
  getCitedDocumentsFromMessage,
  getHumanAndAIMessageFromMessageNumber,
  processRawChatHistory,
} from "../../lib";
import { AIMessage, HumanMessage } from "../../message/Messages";
import { Callout } from "@/components/ui/callout";
import { Separator } from "@/components/ui/separator";
import { useRouter } from "next/navigation";
import { useContext, useEffect, useState } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { OnyxInitializingLoader } from "@/components/OnyxInitializingLoader";
import { Persona } from "@/app/admin/assistants/interfaces";
import { Button } from "@/components/ui/button";
import { OnyxDocument } from "@/lib/search/interfaces";
import TextView from "@/components/chat_search/TextView";
import { ChatFilters } from "../../documentSidebar/ChatFilters";
import { Modal } from "@/components/Modal";
import FunctionalHeader from "@/components/chat_search/Header";
import FixedLogo from "../../shared_chat_search/FixedLogo";
import { useDocumentSelection } from "../../useDocumentSelection";

function BackToOnyxButton({
  documentSidebarToggled,
}: {
  documentSidebarToggled: boolean;
}) {
  const router = useRouter();
  const enterpriseSettings = useContext(SettingsContext)?.enterpriseSettings;

  return (
    <div className="absolute bottom-0 bg-background w-full flex border-t border-border py-4">
      <div className="mx-auto">
        <Button onClick={() => router.push("/chat")}>
          Back to {enterpriseSettings?.application_name || "Onyx Chat"}
        </Button>
      </div>
      <div
        style={{ transition: "width 0.30s ease-out" }}
        className={`
            flex-none 
            overflow-y-hidden 
            transition-all 
            duration-300 
            ease-in-out
            ${documentSidebarToggled ? "w-[400px]" : "w-[0px]"}
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
  const [documentSidebarToggled, setDocumentSidebarToggled] = useState(false);
  const [selectedMessageForDocDisplay, setSelectedMessageForDocDisplay] =
    useState<number | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [presentingDocument, setPresentingDocument] =
    useState<OnyxDocument | null>(null);

  const toggleDocumentSidebar = () => {
    setDocumentSidebarToggled(!documentSidebarToggled);
  };

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
        <BackToOnyxButton documentSidebarToggled={documentSidebarToggled} />
      </div>
    );
  }

  const messages = buildLatestMessageChain(
    processRawChatHistory(chatSession.messages)
  );

  return (
    <>
      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}
      {documentSidebarToggled && settings?.isMobile && (
        <div className="md:hidden">
          <Modal noPadding noScroll>
            <ChatFilters
              isSharedChat={true}
              selectedMessage={
                selectedMessageForDocDisplay
                  ? messages.find(
                      (message) =>
                        message.messageId === selectedMessageForDocDisplay
                    ) || null
                  : null
              }
              toggleDocumentSelection={() => {
                setDocumentSidebarToggled(true);
              }}
              selectedDocuments={[]}
              clearSelectedDocuments={() => {}}
              selectedDocumentTokens={0}
              maxTokens={0}
              initialWidth={400}
              isOpen={true}
              setPresentingDocument={setPresentingDocument}
              modal={true}
              ccPairs={[]}
              tags={[]}
              documentSets={[]}
              showFilters={false}
              closeSidebar={() => {
                setDocumentSidebarToggled(false);
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
                  ${documentSidebarToggled ? "w-[400px]" : "w-[0px]"}
            `}
              >
                <ChatFilters
                  modal={false}
                  isSharedChat={true}
                  selectedMessage={
                    selectedMessageForDocDisplay
                      ? messages.find(
                          (message) =>
                            message.messageId === selectedMessageForDocDisplay
                        ) || null
                      : null
                  }
                  toggleDocumentSelection={() => {
                    setDocumentSidebarToggled(true);
                  }}
                  clearSelectedDocuments={() => {}}
                  selectedDocumentTokens={0}
                  maxTokens={0}
                  initialWidth={400}
                  isOpen={true}
                  setPresentingDocument={setPresentingDocument}
                  ccPairs={[]}
                  tags={[]}
                  documentSets={[]}
                  showFilters={false}
                  closeSidebar={() => {
                    setDocumentSidebarToggled(false);
                  }}
                  selectedDocuments={[]}
                />
              </div>
            )}
            <div className="flex mobile:hidden max-h-full overflow-hidden ">
              <FunctionalHeader
                documentSidebarToggled={documentSidebarToggled}
                sidebarToggled={false}
                toggleSidebar={() => {}}
                page="chat"
                reset={() => {}}
              />
            </div>

            <div className="flex w-full overflow-hidden overflow-y-scroll">
              <div className="w-full h-full   flex-col flex max-w-message-max mx-auto">
                <div className="fixed z-10 w-full ">
                  <div className="bg-background relative px-5 pt-4 w-full">
                    <h1 className="text-3xl text-strong font-bold">
                      {chatSession.description ||
                        `Chat ${chatSession.chat_session_id}`}
                    </h1>
                    <p className=" text-emphasis">
                      {humanReadableFormat(chatSession.time_created)}
                    </p>
                    <div
                      className={`
                      h-full absolute top-0  z-10 w-full sm:w-[90%] lg:w-[70%]
                      bg-gradient-to-b via-50% z-[-1] from-background via-background to-background/10 flex
                      transition-all duration-300 ease-in-out
                      ${
                        documentSidebarToggled
                          ? "left-[200px] transform -translate-x-[calc(50%+100px)]"
                          : "left-1/2 transform -translate-x-1/2"
                      }
                    `}
                    />
                  </div>
                </div>
                {isReady ? (
                  <div className="w-full pt-24 pb-16">
                    {messages.map((message) => {
                      if (message.type === "user") {
                        return (
                          <HumanMessage
                            shared
                            key={message.messageId}
                            content={message.message}
                            files={message.files}
                          />
                        );
                      } else {
                        return (
                          <AIMessage
                            shared
                            query={message.query || undefined}
                            hasDocs={
                              (message.documents &&
                                message.documents.length > 0) === true
                            }
                            toolCall={message.toolCall}
                            docs={message.documents}
                            setPresentingDocument={setPresentingDocument}
                            currentPersona={persona}
                            key={message.messageId}
                            messageId={message.messageId}
                            content={message.message}
                            files={message.files || []}
                            citedDocuments={getCitedDocumentsFromMessage(
                              message
                            )}
                            // toggleDocumentSelection={() => {
                            //   setDocumentSidebarToggled(true);
                            // }}
                            toggleDocumentSelection={() => {
                              if (
                                !documentSidebarToggled ||
                                (documentSidebarToggled &&
                                  selectedMessageForDocDisplay ===
                                    message.messageId)
                              ) {
                                toggleDocumentSidebar();
                              }
                              setSelectedMessageForDocDisplay(
                                message.messageId
                              );
                            }}
                            isComplete
                          />
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
                          ${documentSidebarToggled ? "w-[400px]" : "w-[0px]"}
                      `}
                ></div>
              )}
            </div>
          </div>

          <FixedLogo backgroundToggled={false} />
          <BackToOnyxButton documentSidebarToggled={documentSidebarToggled} />
        </div>
      </div>
    </>
  );
}
