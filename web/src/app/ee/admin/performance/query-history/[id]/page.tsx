"use client";

import { Bold, Text, Card, Title, Divider } from "@tremor/react";
import { ChatSessionSnapshot, MessageSnapshot } from "../../usage/types";
import { FiBook } from "react-icons/fi";
import { timestampToReadableDate } from "@/lib/dateUtils";
import { BackButton } from "@/components/BackButton";
import { FeedbackBadge } from "../FeedbackBadge";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";

function MessageDisplay({ message }: { message: MessageSnapshot }) {
  return (
    <div>
      <Bold className="text-xs mb-1">
        {message.message_type === "user" ? "User" : "AI"}
      </Bold>
      <Text>{message.message}</Text>
      {message.documents.length > 0 && (
        <div className="flex flex-col gap-y-2 mt-2">
          <Bold className="font-bold text-xs">Reference Documents</Bold>
          {message.documents.slice(0, 5).map((document) => {
            return (
              <Text className="flex" key={document.document_id}>
                <FiBook
                  className={
                    "my-auto mr-1" + (document.link ? " text-link" : " ")
                  }
                />
                {document.link ? (
                  <a href={document.link} target="_blank" className="text-link">
                    {document.semantic_identifier}
                  </a>
                ) : (
                  document.semantic_identifier
                )}
              </Text>
            );
          })}
        </div>
      )}
      {message.feedback_type && (
        <div className="mt-2">
          <Bold className="font-bold text-xs">Feedback</Bold>
          {message.feedback_text && <Text>{message.feedback_text}</Text>}
          <FeedbackBadge feedback={message.feedback_type} />
        </div>
      )}
      <Divider />
    </div>
  );
}

export default function QueryPage({ params }: { params: { id: string } }) {
  const {
    data: chatSessionSnapshot,
    isLoading,
    error,
  } = useSWR<ChatSessionSnapshot>(
    `/api/admin/chat-session-history/${params.id}`,
    errorHandlingFetcher
  );

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (!chatSessionSnapshot || error) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch chat session - ${error}`}
      />
    );
  }

  return (
    <main className="pt-4 mx-auto container">
      <BackButton />

      <Card className="mt-4">
        <Title>Chat Session Details</Title>

        <Text className="flex flex-wrap whitespace-normal mt-1 text-xs">
          {chatSessionSnapshot.user_email || "-"},{" "}
          {timestampToReadableDate(chatSessionSnapshot.time_created)}
        </Text>

        <Divider />

        <div className="flex flex-col">
          {chatSessionSnapshot.messages.map((message) => {
            return (
              <MessageDisplay key={message.time_created} message={message} />
            );
          })}
        </div>
      </Card>
    </main>
  );
}
