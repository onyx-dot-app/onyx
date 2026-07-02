"use client";

import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { useStandardAnswerCategories } from "@/app/ee/admin/standard-answer/hooks";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageLoader } from "@/refresh-components/PageLoader";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.STANDARD_ANSWERS;

function Body() {
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
        errorTitle="Something went wrong :("
        errorMsg="Failed to fetch standard answer categories"
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
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title="New Standard Answer"
        backButton
        divider
      />
      <SettingsLayouts.Body>
        <Body />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
