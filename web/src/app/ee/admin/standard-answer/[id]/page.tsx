import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import ResourceErrorPage from "@/sections/error/ResourceErrorPage";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { StandardAnswer, StandardAnswerCategory } from "@/lib/types";

const route = ADMIN_ROUTES.STANDARD_ANSWERS;

async function Main({ id }: { id: string }) {
  const tasks = [
    fetchSS("/manage/admin/standard-answer"),
    fetchSS(`/manage/admin/standard-answer/category`),
  ];
  const [standardAnswersResponse, standardAnswerCategoriesResponse] =
    await Promise.all(tasks);

  if (standardAnswersResponse === undefined) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load standard answers"
        backHref="/admin/standard-answer"
        backLabel="Back to standard answers"
      />
    );
  }

  if (!standardAnswersResponse.ok) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load standard answers"
        description={`Server returned an error: ${await standardAnswersResponse.text()}`}
        backHref="/admin/standard-answer"
        backLabel="Back to standard answers"
      />
    );
  }
  const allStandardAnswers =
    (await standardAnswersResponse.json()) as StandardAnswer[];
  const standardAnswer = allStandardAnswers.find(
    (answer) => answer.id.toString() === id
  );

  if (!standardAnswer) {
    return (
      <ResourceErrorPage
        errorType="not_found"
        title="Standard answer not found"
        description={`Standard answer with ID ${id} could not be found.`}
        backHref="/admin/standard-answer"
        backLabel="Back to standard answers"
      />
    );
  }

  if (standardAnswerCategoriesResponse === undefined) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load standard answer categories"
        backHref="/admin/standard-answer"
        backLabel="Back to standard answers"
      />
    );
  }

  if (!standardAnswerCategoriesResponse.ok) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load standard answer categories"
        description={`Server returned an error: ${await standardAnswerCategoriesResponse.text()}`}
        backHref="/admin/standard-answer"
        backLabel="Back to standard answers"
      />
    );
  }

  const standardAnswerCategories =
    (await standardAnswerCategoriesResponse.json()) as StandardAnswerCategory[];

  return (
    <StandardAnswerCreationForm
      standardAnswerCategories={standardAnswerCategories}
      existingStandardAnswer={standardAnswer}
    />
  );
}

export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;

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
