"use client";
import { use } from "react";

import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Title from "@/components/ui/title";
import useSWR from "swr";
import { IndexAttemptErrorsTable } from "./IndexAttemptErrorsTable";
import { buildIndexingErrorsUrl } from "./lib";
import { IndexAttemptError } from "./types";

function Main({ id }: { id: number }) {
  const {
    data: indexAttemptErrors,
    isLoading,
    error,
  } = useSWR<IndexAttemptError[]>(
    buildIndexingErrorsUrl(id),
    errorHandlingFetcher
  );

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (error || !indexAttemptErrors) {
    return (
      <ErrorCallout
        errorTitle={`Failed to fetch errors for attempt ID ${id}`}
        errorMsg={error?.info?.detail || error.toString()}
      />
    );
  }

  return (
    <>
      <BackButton />
      <div className="mt-6">
        <div className="flex">
          <Title>Indexing Errors for Attempt {id}</Title>
        </div>
        <IndexAttemptErrorsTable indexAttemptErrors={indexAttemptErrors} />
      </div>
    </>
  );
}

export default function Page(props: { params: Promise<{ id: string }> }) {
  const params = use(props.params);
  const id = parseInt(params.id);

  return (
    <div className="mx-auto container">
      <Main id={id} />
    </div>
  );
}
