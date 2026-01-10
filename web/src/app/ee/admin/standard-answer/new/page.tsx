import { AdminPageTitle } from "@/components/admin/Title";
import { StandardAnswerCreationForm } from "@/app/ee/admin/standard-answer/StandardAnswerCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import BackButton from "@/refresh-components/buttons/BackButton";
import { ClipboardIcon } from "@/components/icons/icons";
import { StandardAnswerCategory } from "@/lib/types";

async function Page() {
  const standardAnswerCategoriesResponse = await fetchSS(
    "/manage/admin/standard-answer/category"
  );

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
    <>
      <BackButton />
      <AdminPageTitle
        title="New Standard Answer"
        icon={<ClipboardIcon size={32} />}
      />

      <StandardAnswerCreationForm
        standardAnswerCategories={standardAnswerCategories}
      />
    </>
  );
}

export default Page;
