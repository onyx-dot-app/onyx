"use client";

import { useState } from "react";
import { humanReadableFormat } from "@/lib/time";
import { BackendChatSession } from "@/app/app/interfaces";
import { processRawChatHistory } from "@/app/app/services/lib";
import { getLatestMessageChain } from "@/app/app/services/messageTree";
import HumanMessage from "@/app/app/message/HumanMessage";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import OnyxInitializingLoader from "@/components/OnyxInitializingLoader";
import { Section } from "@/layouts/general-layouts";
import { IllustrationContent } from "@opal/layouts";
import SvgNotFound from "@opal/illustrations/not-found";
import { Button } from "@opal/components";
import { Persona } from "@/app/admin/agents/interfaces";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import PreviewModal from "@/sections/modals/PreviewModal";
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
      <div className="h-full w-full flex flex-col items-center justify-center">
        <Section flexDirection="column" alignItems="center" gap={1}>
          <IllustrationContent
            illustration={SvgNotFound}
            title="Shared chat not found"
            description="Did not find a shared chat with the specified ID."
          />
          <Button href="/app" prominence="secondary">
            Start a new chat
          </Button>
        </Section>
      </div>
    );
  }

  const messages = getLatestMessageChain(
    processRawChatHistory(chatSession.messages, chatSession.packets)
  );

  const firstMessage = messages[0];

  if (firstMessage === undefined) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center">
        <Section flexDirection="column" alignItems="center" gap={1}>
          <IllustrationContent
            illustration={SvgNotFound}
            title="Shared chat not found"
            description="No messages found in shared chat."
          />
          <Button href="/app" prominence="secondary">
            Start a new chat
          </Button>
        </Section>
      </div>
    );
  }

  return (
    <>
      {presentingDocument && (
        <PreviewModal
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
                        agent: persona,
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
