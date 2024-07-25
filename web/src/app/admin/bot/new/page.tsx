import { AdminPageTitle } from "@/components/admin/Title";
import { CPUIcon } from "@/components/icons/icons";
import { SlackBotCreationForm } from "../SlackBotConfigCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { DocumentSet, StandardAnswerCategory } from "@/lib/types";
import { BackButton } from "@/components/BackButton";
import { Text } from "@tremor/react";
import {
  FetchAssistantsResponse,
  fetchAssistantsSS,
} from "@/lib/assistants/fetchAssistantsSS";

async function Page() {
  const tasks = [
    fetchSS("/manage/document-set"),
    fetchAssistantsSS(),
    fetchSS("/manage/admin/standard-answer/category"),
  ];
  const [
    documentSetsResponse,
    [assistants, assistantsFetchError],
    standardAnswerCategoriesResponse,
  ] = (await Promise.all(tasks)) as [
    Response,
    FetchAssistantsResponse,
    Response,
  ];

  if (!documentSetsResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch document sets - ${await documentSetsResponse.text()}`}
      />
    );
  }
  const documentSets = (await documentSetsResponse.json()) as DocumentSet[];

  if (assistantsFetchError) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch assistants - ${assistantsFetchError}`}
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
        icon={<CPUIcon size={32} />}
        title="New Slack Bot Config"
      />

      <Text className="mb-8">
        Define a new configuration below! This config will determine how
        DanswerBot behaves in the specified channels.
      </Text>

      <SlackBotCreationForm
        documentSets={documentSets}
        personas={assistants}
        standardAnswerCategories={standardAnswerCategories}
      />
    </div>
  );
}

export default Page;
