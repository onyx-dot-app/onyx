import i18n from "@/i18n/init";
import k from "./../../../../../i18n/keys";
import { AdminPageTitle } from "@/components/admin/Title";
import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { BackButton } from "@/components/BackButton";
import { ClipboardIcon } from "@/components/icons/icons";
import { StandardAnswerCategory } from "@/lib/types";

async function Page() {
  const standardAnswerCategoriesResponse = await fetchSS(
    "/manage/admin/standard-answer/category"
  );

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
        title={i18n.t(k.NEW_STANDARD_ANSWER)}
        icon={<ClipboardIcon size={32} />}
      />

      <StandardAnswerCreationForm
        standardAnswerCategories={standardAnswerCategories}
      />
    </div>
  );
}

export default Page;
