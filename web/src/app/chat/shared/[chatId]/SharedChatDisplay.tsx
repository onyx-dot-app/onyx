"use client";
import Prism from "prismjs";

import { humanReadableFormat } from "@/lib/time";
import { BackendChatSession } from "../../interfaces";
import {
  buildLatestMessageChain,
  getCitedDocumentsFromMessage,
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

function BackToOnyxButton() {
  const router = useRouter();
  const enterpriseSettings = useContext(SettingsContext)?.enterpriseSettings;

  return (
    <div className="absolute bottom-0 bg-background w-full flex border-t border-border py-4">
      <div className="mx-auto">
        <Button onClick={() => router.push("/chat")}>
          Back to GPT Lab Chat
        </Button>
      </div>
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
  const [isReady, setIsReady] = useState(false);
  const [presentingDocument, setPresentingDocument] =
    useState<OnyxDocument | null>(null);

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
        <BackToOnyxButton />
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
      <div className="w-full h-[100dvh] overflow-hidden">
        <div className="flex max-h-full overflow-hidden pb-[72px]">
          <div className="flex w-full overflow-hidden overflow-y-scroll">
            <div className="w-full h-full flex-col flex max-w-message-max mx-auto">
              <div className="px-5 pt-8">
                <h1 className="text-3xl text-strong font-bold">
                  {chatSession.description ||
                    `Chat ${chatSession.chat_session_id}`}
                </h1>
                <p className="text-emphasis">
                  {humanReadableFormat(chatSession.time_created)}
                </p>

                <Separator />
              </div>
              {isReady ? (
                <div className="w-full pb-16">
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
                          setPresentingDocument={setPresentingDocument}
                          currentPersona={persona}
                          key={message.messageId}
                          messageId={message.messageId}
                          content={message.message}
                          files={message.files || []}
                          citedDocuments={getCitedDocumentsFromMessage(message)}
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
          </div>
        </div>

        <BackToOnyxButton />
      </div>
    </>
  );
}
