"use client";

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
import { Persona } from "@/app/admin/assistants/interfaces";

function BackToDanswerButton() {
  const router = useRouter();

  return (
    <div className="absolute bottom-4 w-full flex border-t border-border pt-4">
      <div className="mx-auto">
        <Button onClick={() => router.push("/chat")}>
          Back to Danswer Chat
        </Button>
      </div>
    </div>
  );
}

export function SharedChatDisplay({
  chatSession,
  availableAssistants,
}: {
  chatSession: BackendChatSession | null;
  availableAssistants: Persona[];
}) {
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

  const currentPersona = availableAssistants.find(
    (persona) => persona.id === chatSession.persona_id
  );

  const messages = buildLatestMessageChain(
    processRawChatHistory(chatSession.messages)
  );

  return (
    <div className="w-full overflow-hidden">
      <div className="flex max-h-full overflow-hidden pb-[72px]">
        <div className="flex w-full overflow-hidden overflow-y-scroll">
          <div className="mx-auto">
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

            <div className="pb-16">
              {messages.map((message) => {
                if (message.type === "user") {
                  return (
                    <HumanMessage
                      key={message.messageId}
                      content={message.message}
                    />
                  );
                } else {
                  return (
                    <AIMessage
                      currentPersona={currentPersona!}
                      key={message.messageId}
                      messageId={message.messageId}
                      content={message.message}
                      personaName={chatSession.persona_name}
                      citedDocuments={getCitedDocumentsFromMessage(message)}
                      isComplete
                    />
                  );
                }
              })}
            </div>
          </div>
        </div>
      </div>

      <BackToDanswerButton />
    </div>
  );
}
