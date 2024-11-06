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
import { Button, Callout, Divider } from "@tremor/react";
import { useRouter } from "next/navigation";
import { useContext, useEffect, useState } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { DanswerInitializingLoader } from "@/components/DanswerInitializingLoader";
import { Persona } from "@/app/admin/assistants/interfaces";

function BackToDanswerButton() {
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
  useEffect(() => {
    Prism.highlightAll();
    setIsReady(true);
  }, []);
  if (!chatSession) {
    return (
      <div className="min-h-full w-full">
        <div className="mx-auto w-fit pt-8">
          <Callout color="red" title="Shared Chat Not Found">
            Did not find a shared chat with the specified ID.
          </Callout>
        </div>
        <BackToDanswerButton />
      </div>
    );
  }

  const messages = buildLatestMessageChain(
    processRawChatHistory(chatSession.messages)
  );

  return (
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

              <Divider />
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
                  <DanswerInitializingLoader />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <BackToDanswerButton />
    </div>
  );
}
