import { AdminPageTitle } from "@/components/admin/Title";
import { CPUIcon } from "@/components/icons/icons";
import { SlackBotCreationForm } from "../SlackBotConfigCreationForm";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { DocumentSet, SlackBotConfig } from "@/lib/types";
import Text from "@/components/ui/text";
import { BackButton } from "@/components/BackButton";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import {
  FetchAssistantsResponse,
  fetchAssistantsSS,
} from "@/lib/assistants/fetchAssistantsSS";
import { getStandardAnswerCategoriesIfEE } from "@/components/standardAnswers/getStandardAnswerCategoriesIfEE";

async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  const tasks = [
    fetchSS("/manage/admin/slack-bot/config"),
    fetchSS("/manage/document-set"),
    fetchAssistantsSS(),
  ];

  const [
    slackBotsResponse,
    documentSetsResponse,
    [assistants, assistantsFetchError],
  ] = (await Promise.all(tasks)) as [
    Response,
    Response,
    FetchAssistantsResponse,
  ];

  const eeStandardAnswerCategoryResponse =
    await getStandardAnswerCategoriesIfEE();

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
        standardAnswerCategoryResponse={eeStandardAnswerCategoryResponse}
        existingSlackBotConfig={slackBotConfig}
      />
    </div>
  );
}

export default Page;
