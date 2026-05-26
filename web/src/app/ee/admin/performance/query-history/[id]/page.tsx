"use client";
import { use } from "react";

import { ChatSessionSnapshot } from "../../usage/types";
import BackButton from "@/refresh-components/buttons/BackButton";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import CardSection from "@/components/admin/CardSection";
import { QueryHistorySessionDetail } from "@/app/ee/admin/performance/query-history/QueryHistorySessionDetail";

export default function QueryPage(props: { params: Promise<{ id: string }> }) {
  const params = use(props.params);
  const {
    data: chatSessionSnapshot,
    isLoading,
    error,
  } = useSWR<ChatSessionSnapshot>(
    SWR_KEYS.adminChatSession(params.id),
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

      <CardSection className="mt-4">
        <QueryHistorySessionDetail chatSessionSnapshot={chatSessionSnapshot} />
      </CardSection>
    </main>
  );
}
