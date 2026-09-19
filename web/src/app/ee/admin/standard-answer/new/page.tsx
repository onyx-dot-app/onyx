"use client";

import { useTranslations } from "next-intl";
import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { useStandardAnswerCategories } from "@/app/ee/admin/standard-answer/hooks";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageLoader } from "@opal/layouts";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.STANDARD_ANSWERS;

function Body() {
  const t = useTranslations("admin.standardAnswers");
  const {
    data: standardAnswerCategories,
    isLoading,
    error,
  } = useStandardAnswerCategories();

  if (isLoading) {
    return <PageLoader />;
  }

  if (error || !standardAnswerCategories) {
    return (
      <ErrorCallout
        errorTitle={t("errors.genericTitle.title")}
        errorMsg={t("errors.fetchCategoriesFailed.message")}
      />
    );
  }

  return (
    <StandardAnswerCreationForm
      standardAnswerCategories={standardAnswerCategories}
    />
  );
}

export default function Page() {
  const t = useTranslations("admin.standardAnswers");
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("newStandardAnswer.label")}
        backButton
        divider
      />
      <SettingsLayouts.Body>
        <Body />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
