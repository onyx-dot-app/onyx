import i18n from "@/i18n/init-server";
import k from "@/i18n/keys";
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
  if (!standardAnswersResponse.ok) {
    return (
      <ErrorCallout
        errorTitle={i18n.t(k.SOMETHING_WENT_WRONG)}
        errorMsg={`${i18n.t(
          k.FAILED_TO_FETCH_STANDARD_ANSWE1
        )} ${await standardAnswersResponse.text()}`}
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
        errorTitle={i18n.t(k.SOMETHING_WENT_WRONG)}
        errorMsg={`${i18n.t(k.DID_NOT_FIND_STANDARD_ANSWER_W)} ${params.id}`}
      />
    );
  }

  if (!standardAnswerCategoriesResponse.ok) {
    return (
      <ErrorCallout
        errorTitle={i18n.t(k.SOMETHING_WENT_WRONG)}
        errorMsg={`${i18n.t(
          k.FAILED_TO_FETCH_STANDARD_ANSWE
        )} ${await standardAnswerCategoriesResponse.text()}`}
      />
    );
  }

  const standardAnswerCategories =
    (await standardAnswerCategoriesResponse.json()) as StandardAnswerCategory[];
  return (
    <div className="container mx-auto">
      <BackButton />
      <AdminPageTitle
        title={i18n.t(k.EDIT_STANDARD_ANSWER)}
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
