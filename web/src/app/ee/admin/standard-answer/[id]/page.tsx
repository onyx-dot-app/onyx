import { AdminPageTitle } from "@/components/admin/Title";
import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { BackButton } from "@/components/BackButton";
import { ClipboardIcon } from "@/components/icons/icons";
import { StandardAnswer, StandardAnswerCategory } from "@/lib/types";

async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  const tasks = [
    fetchSS("/manage/admin/standard-answer"),
    fetchSS(`/manage/admin/standard-answer/category`),
  ];
  const [standardAnswersResponse, standardAnswerCategoriesResponse] =
    await Promise.all(tasks);

  if (standardAnswersResponse === undefined) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answers.`}
      />
    );
  }

  if (!standardAnswersResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answers - ${await standardAnswersResponse.text()}`}
      />
    );
  }
  const allStandardAnswers =
    (await standardAnswersResponse.json()) as StandardAnswer[];
  const standardAnswer = allStandardAnswers.find(
    (answer) => answer.id.toString() === params.id
  );

  if (!standardAnswer) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Did not find standard answer with ID: ${params.id}`}
      />
    );
  }

  if (standardAnswerCategoriesResponse === undefined) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answer categories.`}
      />
    );
  }

  if (!standardAnswerCategoriesResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch standard answer categories - ${await standardAnswerCategoriesResponse.text()}`}
      />
    );
  }

  const standardAnswerCategories =
    (await standardAnswerCategoriesResponse.json()) as StandardAnswerCategory[];
  return (
    <div className="container mx-auto">
      <BackButton />
      <AdminPageTitle
        title="Edit Standard Answer"
        icon={<ClipboardIcon size={32} />}
      />

      <StandardAnswerCreationForm
        standardAnswerCategories={standardAnswerCategories}
        existingStandardAnswer={standardAnswer}
      />
    </div>
  );
}

export default Page;
