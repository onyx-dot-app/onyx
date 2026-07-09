"use client";

import { useParams } from "next/navigation";
import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import {
  useStandardAnswers,
  useStandardAnswerCategories,
} from "@/app/ee/admin/standard-answer/hooks";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageLoader } from "@/refresh-components/PageLoader";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.STANDARD_ANSWERS;

function Body({ id }: { id: string }) {
  const {
    data: standardAnswers,
    isLoading: answersLoading,
    error: answersError,
  } = useStandardAnswers();
  const {
    data: standardAnswerCategories,
    isLoading: categoriesLoading,
    error: categoriesError,
  } = useStandardAnswerCategories();

  if (answersLoading || categoriesLoading) {
    return <PageLoader />;
  }

  if (answersError || categoriesError || !standardAnswerCategories) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg="Failed to fetch standard answers"
      />
    );
  }

  const standardAnswer = standardAnswers?.find(
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

  return (
    <StandardAnswerCreationForm
      standardAnswerCategories={standardAnswerCategories}
      existingStandardAnswer={standardAnswer}
    />
  );
}

export default function Page() {
  const params = useParams<{ id: string }>();

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title="Edit Standard Answer"
        backButton
        divider
      />
      <SettingsLayouts.Body>
        <Body id={params.id} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
