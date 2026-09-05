"use client";

import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import {
  useStandardAnswers,
  useStandardAnswerCategories,
} from "@/app/ee/admin/standard-answer/hooks";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageLoader } from "@opal/layouts";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.STANDARD_ANSWERS;

function Body({ id }: { id: string }) {
  const t = useTranslations("admin.standardAnswers");
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
        errorTitle={t("errors.genericTitle.title")}
        errorMsg={t("errors.fetchAnswersFailed.message")}
      />
    );
  }

  const standardAnswer = standardAnswers?.find(
    (answer) => answer.id.toString() === id
  );

  if (!standardAnswer) {
    return (
      <ErrorCallout
        errorTitle={t("errors.genericTitle.title")}
        errorMsg={t("errors.notFound.message", { id })}
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
  const t = useTranslations("admin.standardAnswers");
  const params = useParams<{ id: string }>();

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("editPage.title")}
        backButton
        divider
      />
      <SettingsLayouts.Body>
        <Body id={params.id} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
