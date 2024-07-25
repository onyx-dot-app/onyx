import { AdminPageTitle } from "@/components/admin/Title";
import { CPUIcon } from "@/components/icons/icons";
import { SlackBotCreationForm } from "../SlackBotConfigCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import {
  DocumentSet,
  SlackBotConfig,
  StandardAnswerCategory,
} from "@/lib/types";
import { Text } from "@tremor/react";
import { BackButton } from "@/components/BackButton";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import {
  FetchAssistantsResponse,
  fetchAssistantsSS,
} from "@/lib/assistants/fetchAssistantsSS";

async function Page({ params }: { params: { id: string } }) {
  const tasks = [
    fetchSS("/manage/admin/slack-bot/config"),
    fetchSS("/manage/document-set"),
    fetchAssistantsSS(),
    fetchSS("/manage/admin/standard-answer/category"),
  ];

  const [
    slackBotsResponse,
    documentSetsResponse,
    [assistants, assistantsFetchError],
    standardAnswerCategoriesResponse,
  ] = (await Promise.all(tasks)) as [
    Response,
    Response,
    FetchAssistantsResponse,
    Response,
  ];

  if (!slackBotsResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch slack bots - ${await slackBotsResponse.text()}`}
      />
    );
  }
  const allSlackBotConfigs =
    (await slackBotsResponse.json()) as SlackBotConfig[];
  const slackBotConfig = allSlackBotConfigs.find(
    (config) => config.id.toString() === params.id
  );
  if (!slackBotConfig) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Did not find Slack Bot config with ID: ${params.id}`}
      />
    );
  }

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
        errorMsg={`Failed to fetch personas - ${assistantsFetchError}`}
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
      <InstantSSRAutoRefresh />

      <BackButton />
      <AdminPageTitle
        icon={<CPUIcon size={32} />}
        title="Edit Slack Bot Config"
      />

      <Text className="mb-8">
        Edit the existing configuration below! This config will determine how
        DanswerBot behaves in the specified channels.
      </Text>

      <SlackBotCreationForm
        documentSets={documentSets}
        personas={assistants}
        standardAnswerCategories={standardAnswerCategories}
        existingSlackBotConfig={slackBotConfig}
      />
    </div>
  );
}

export default Page;
