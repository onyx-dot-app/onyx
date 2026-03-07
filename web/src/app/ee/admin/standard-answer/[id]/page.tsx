"use client";

import { use } from "react";
import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTE_CONFIG, ADMIN_PATHS } from "@/lib/admin-routes";
import { useStandardAnswers, useStandardAnswerCategories } from "../hooks";

const route = ADMIN_ROUTE_CONFIG[ADMIN_PATHS.STANDARD_ANSWERS]!;

function Main({ id }: { id: string }) {
  const {
    data: standardAnswers,
    isLoading: isAnswersLoading,
    error: answersError,
  } = useStandardAnswers();

  const {
    data: standardAnswerCategories,
    isLoading: isCategoriesLoading,
    error: categoriesError,
  } = useStandardAnswerCategories();

  if (isAnswersLoading || isCategoriesLoading) {
    return <ThreeDotsLoader />;
  }

  if (answersError || !standardAnswers) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answers - ${
          answersError?.message ?? "unknown error"
        }`}
      />
    );
  }

  const standardAnswer = standardAnswers.find(
    (answer) => answer.id.toString() === id
  );

  if (!standardAnswer) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Did not find standard answer with ID: ${id}`}
      />
    );
  }

  if (categoriesError || !standardAnswerCategories) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answer categories - ${
          categoriesError?.message ?? "unknown error"
        }`}
      />
    );
  }

  return (
    <StandardAnswerCreationForm
      standardAnswerCategories={standardAnswerCategories}
      existingStandardAnswer={standardAnswer}
    />
  );
}

export default function Page(props: { params: Promise<{ id: string }> }) {
  const params = use(props.params);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title="Edit Standard Answer"
        backButton
        separator
      />
      <SettingsLayouts.Body>
        <Main id={params.id} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
