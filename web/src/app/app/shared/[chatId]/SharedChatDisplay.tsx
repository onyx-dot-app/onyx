"use client";

import { useState } from "react";
import { humanReadableFormat } from "@/lib/time";
import { BackendChatSession } from "@/app/app/interfaces";
import { processRawChatHistory } from "@/app/app/services/lib";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import HumanMessage from "@/app/app/message/HumanMessage";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import { Callout } from "@/components/ui/callout";
import OnyxInitializingLoader from "@/components/OnyxInitializingLoader";
import { Persona } from "@/app/admin/assistants/interfaces";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import TextViewModal from "@/sections/modals/TextViewModal";
import { UNNAMED_CHAT } from "@/lib/constants";
import Text from "@/refresh-components/texts/Text";
import useOnMount from "@/hooks/useOnMount";
import SharedAppInputBar from "@/sections/input/SharedAppInputBar";

export interface SharedChatDisplayProps {
  chatSession: BackendChatSession | null;
  persona: Persona;
}

export default function SharedChatDisplay({
  chatSession,
  persona,
}: SharedChatDisplayProps) {
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  const isMounted = useOnMount();

  if (!chatSession) {
    return (
      <div className="min-h-full w-full">
        <div className="mx-auto w-fit pt-8">
          <Callout type="danger" title="Shared Chat Not Found">
            Did not find a shared chat with the specified ID.
          </Callout>
        </div>
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
      </div>
    );
  }

  return (
    <>
      {presentingDocument && (
        <TextViewModal
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}

      <div className="flex flex-col h-full w-full overflow-hidden">
        <div className="flex-1 flex flex-col items-center overflow-y-auto">
          <div className="sticky top-0 z-10 flex items-center justify-between w-full bg-background-tint-01 px-8 py-4">
            <Text as="p" text04 headingH2>
              {chatSession.description || UNNAMED_CHAT}
            </Text>
            <div className="flex flex-col items-end">
              <Text as="p" text03 secondaryBody>
                Shared on {humanReadableFormat(chatSession.time_created)}
              </Text>
              {chatSession.owner_name && (
                <Text as="p" text03 secondaryBody>
                  by {chatSession.owner_name}
                </Text>
              )}
            </div>
          </div>

          {isMounted ? (
            <div className="w-[min(50rem,100%)]">
              {messages.map((message, i) => {
                if (message.type === "user") {
                  return (
                    <HumanMessage
                      key={message.messageId}
                      content={message.message}
                      files={message.files}
                      nodeId={message.nodeId}
                    />
                  );
                } else if (message.type === "assistant") {
                  return (
                    <AgentMessage
                      key={message.messageId}
                      rawPackets={message.packets}
                      chatState={{
                        assistant: persona,
                        docs: message.documents,
                        citations: message.citations,
                        setPresentingDocument: setPresentingDocument,
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
                    <div key={message.messageId} className="py-5 ml-4 lg:px-5">
                      <div className="mx-auto w-[90%] max-w-message-max">
                        <p className="text-status-text-error-05 text-sm my-auto">
                          {message.message}
                        </p>
                      </div>
                    </div>
                  );
                }
              })}
            </div>
          ) : (
            <div className="h-full w-full flex items-center justify-center">
              <OnyxInitializingLoader />
            </div>
          )}
        </div>

        <div className="w-full max-w-[50rem] mx-auto px-4 pb-4">
          <SharedAppInputBar />
        </div>
      </div>
    </>
  );
}
