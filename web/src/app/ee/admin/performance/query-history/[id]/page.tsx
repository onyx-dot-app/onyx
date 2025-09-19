"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "@/i18n/keys";
import { use } from "react";

import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Separator } from "@/components/ui/separator";
import { ChatSessionSnapshot, MessageSnapshot } from "../../usage/types";
import { FiBook } from "react-icons/fi";
import { timestampToReadableDate } from "@/lib/dateUtils";
import { BackButton } from "@/components/BackButton";
import { FeedbackBadge } from "../FeedbackBadge";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import CardSection from "@/components/admin/CardSection";

function MessageDisplay({ message }: { message: MessageSnapshot }) {
  const { t } = useTranslation();
  return (
    <div>
      <p className="text-xs font-bold mb-1">
        {message.message_type === "user" ? t(k.USER) : t(k.AI)}
      </p>
      <Text>{message.message}</Text>
      {message.documents.length > 0 && (
        <div className="flex flex-col gap-y-2 mt-2">
          <p className="font-bold text-xs">{t(k.REFERENCE_DOCUMENTS)}</p>
          {message.documents.slice(0, 5).map((document) => {
            return (
              <Text className="flex" key={document.document_id}>
                <FiBook
                  className={
                    "my-auto mr-1" + (document.link ? " text-link" : " ")
                  }
                />

                {document.link ? (
                  <a
                    href={document.link}
                    target="_blank"
                    className="text-link"
                    rel="noreferrer"
                  >
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
          <p className="font-bold text-xs">{t(k.FEEDBACK)}</p>
          {message.feedback_text && <Text>{message.feedback_text}</Text>}
          <div className="mt-1">
            <FeedbackBadge feedback={message.feedback_type} />
          </div>
        </div>
      )}
      <Separator />
    </div>
  );
}

export default function QueryPage(props: { params: Promise<{ id: string }> }) {
  const { t } = useTranslation();
  const params = use(props.params);
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
        errorTitle={t(k.SOMETHING_WENT_WRONG)}
        errorMsg={`${t(k.FAILED_TO_FETCH_CHAT_SESSION)} ${error}`}
      />
    );
  }

  return (
    <main className="pt-4 mx-auto container">
      <BackButton />

      <CardSection className="mt-4">
        <Title>{t(k.CHAT_SESSION_DETAILS)}</Title>

        <Text className="flex flex-wrap whitespace-normal mt-1 text-xs">
          {chatSessionSnapshot.user_email &&
            `${chatSessionSnapshot.user_email}${t(k._3)} `}
          {timestampToReadableDate(chatSessionSnapshot.time_created)}
          {t(k._3)} {chatSessionSnapshot.flow_type}
        </Text>

        <Separator />

        <div className="flex flex-col">
          {chatSessionSnapshot.messages.map((message) => {
            return <MessageDisplay key={message.id} message={message} />;
          })}
        </div>
      </CardSection>
    </main>
  );
}
