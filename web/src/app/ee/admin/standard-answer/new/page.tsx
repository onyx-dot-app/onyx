"use client";

import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTE_CONFIG, ADMIN_PATHS } from "@/lib/admin-routes";
import { useStandardAnswerCategories } from "../hooks";

const route = ADMIN_ROUTE_CONFIG[ADMIN_PATHS.STANDARD_ANSWERS]!;

function Main() {
  const {
    data: standardAnswerCategories,
    isLoading,
    error,
  } = useStandardAnswerCategories();

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (error || !standardAnswerCategories) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answer categories - ${
          error?.message ?? "unknown error"
        }`}
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
        separator
      />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
